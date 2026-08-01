from __future__ import annotations

import io

import pytest
from PIL import Image

from edmg_studio_backend import app as studio_app
from edmg_studio_backend.services import imagineart_platform as ia
from edmg_studio_backend.services.imagineart_platform import ImagineArtClient
from edmg_studio_backend.services.render_settings import (
    VIDEO_GENERATION_PREFERENCES,
    RenderSettingsStore,
)
from edmg_studio_backend.store.projects import ProjectStore


class _FakeResp:
    def __init__(self, status_code=200, json_data=None, content=b"", headers=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.content = content
        self.headers = headers or {}
        self.text = ""

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


class _FakeRequests:
    def __init__(self):
        self.poll_calls = 0
        self.posted = []

    def post(self, url, **kwargs):
        self.posted.append({"url": url, **kwargs})
        if "/image/generations" in url:
            img = Image.new("RGB", (512, 512), color=(10, 20, 30))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return _FakeResp(200, content=buf.getvalue(), headers={"Content-Type": "image/png"})
        if "/video/text-to-video" in url:
            return _FakeResp(200, {"id": "vid-1", "status": "pending"})
        if "/video/image-to-video" in url:
            return _FakeResp(200, {"id": "vid-2", "status": "pending"})
        raise AssertionError(f"unexpected POST {url}")

    def get(self, url, **kwargs):
        if "/video/" in url and "/status" in url:
            self.poll_calls += 1
            if self.poll_calls < 2:
                return _FakeResp(200, {"status": "processing"})
            return _FakeResp(
                200,
                {
                    "status": "success",
                    "video": {
                        "url": {
                            "generation": ["https://cdn.example/clip.mp4"],
                            "thumbnail": ["https://cdn.example/thumb.jpg"],
                        }
                    },
                },
            )
        if "cdn.example" in url or url.endswith(".mp4"):
            return _FakeResp(200, content=b"MP4DATA", headers={"Content-Type": "video/mp4"})
        raise AssertionError(f"unexpected GET {url}")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(ia.time, "sleep", lambda *_a, **_k: None)


def test_generate_image_returns_pil_image(monkeypatch):
    fake = _FakeRequests()
    monkeypatch.setattr(ia, "requests", fake)

    client = ImagineArtClient(api_key="test-key")
    result = client.generate_image(prompt="neon skyline", width=768, height=432, style="realistic")

    assert result.image.size == (768, 432)
    assert result.model == "realistic"
    assert fake.posted[0]["url"].endswith("/image/generations")


def test_generate_video_text_to_video(monkeypatch):
    fake = _FakeRequests()
    monkeypatch.setattr(ia, "requests", fake)

    client = ImagineArtClient(api_key="test-key")
    result = client.generate_video(prompt="flying dinosaur", style="kling-1.0-pro", poll_interval_s=0.0)

    assert result.video_bytes == b"MP4DATA"
    assert result.content_type == "video/mp4"
    assert result.model == "kling-1.0-pro"
    assert result.generation_id == "vid-1"
    assert fake.poll_calls >= 2


def test_generate_video_image_to_video(monkeypatch):
    fake = _FakeRequests()
    monkeypatch.setattr(ia, "requests", fake)

    init = Image.new("RGB", (640, 360), color=(255, 0, 0))
    client = ImagineArtClient(api_key="test-key")
    result = client.generate_video(
        prompt="animate this",
        init_image=init,
        poll_interval_s=0.0,
    )

    assert result.video_bytes == b"MP4DATA"
    assert "/video/image-to-video" in fake.posted[0]["url"]


def test_missing_api_key_raises():
    with pytest.raises(ia.UserFacingError) as exc:
        ImagineArtClient(api_key="")
    assert exc.value.code == "IMAGINEART_API_KEY_MISSING"


def test_render_settings_exposes_imagineart(tmp_path):
    assert "imagineart_cloud" in VIDEO_GENERATION_PREFERENCES
    store = RenderSettingsStore(tmp_path)
    saved = store.update({
        "imagineart": {
            "enabled": True,
            "image_style": "anime",
            "video_style": "imagine-v2",
            "video_enabled": True,
            "timeout_s": 9999,
        }
    })
    assert saved["imagineart"]["enabled"] is True
    assert saved["imagineart"]["image_style"] == "anime"
    assert saved["imagineart"]["video_style"] == "imagine-v2"
    assert saved["imagineart"]["timeout_s"] == 1800


@pytest.mark.parametrize(
    ("route", "provider", "stem"),
    [
        (studio_app.render_firefly_assemble, "adobe-firefly", "firefly_v0_muxed"),
        (studio_app.render_imagineart_assemble, "imagineart", "imagineart_v0_muxed"),
    ],
)
@pytest.mark.parametrize("audio_layout", ["uploaded", "legacy_fallback"])
def test_hosted_assemble_uses_project_dir_and_muxes_audio(
    tmp_path,
    monkeypatch,
    route,
    provider,
    stem,
    audio_layout,
):
    store = ProjectStore(tmp_path / "data")
    proj = store.create("Hosted assemble")
    proj.meta = {
        "last_plan": {
            "variants": [
                {
                    "name": "v1",
                    "scenes": [
                        {"start_s": 0.0, "end_s": 1.25, "prompt": "neon skyline"},
                    ],
                }
            ]
        }
    }
    project_dir = store.project_dir(proj.id)
    if audio_layout == "uploaded":
        audio_path = project_dir / "assets" / "audio" / "soundtrack.wav"
        proj.meta["audio"] = {"filename": audio_path.name}
    else:
        audio_path = project_dir / "audio.wav"
    store.save(proj)
    stills_dir = project_dir / "stills" / "variant_0"
    stills_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), color=(10, 20, 30)).save(stills_dir / "scene_0000.png")
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"audio")

    calls: dict[str, object] = {}

    def fake_assemble_slideshow(*, ffmpeg_path, image_paths, durations_s, out_mp4, fps):
        calls["assemble"] = {
            "image_paths": list(image_paths),
            "durations_s": list(durations_s),
            "out_path": out_mp4,
            "fps": fps,
        }
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        out_mp4.write_bytes(b"video")

    def fake_mux_audio(ffmpeg_path, video_mp4, audio_path, out_mp4):
        calls["mux"] = {
            "video_mp4": video_mp4,
            "audio_path": audio_path,
            "out_mp4": out_mp4,
        }
        assert video_mp4.exists()
        assert audio_path == expected_audio_path
        out_mp4.write_bytes(video_mp4.read_bytes() + b"+audio")

    expected_audio_path = audio_path

    monkeypatch.setattr(studio_app, "store", store)
    monkeypatch.setattr(studio_app, "assemble_slideshow", fake_assemble_slideshow)
    monkeypatch.setattr(studio_app, "mux_audio", fake_mux_audio)

    result = route(proj.id, {"variant_index": 0, "fps": 24})

    assert result["ok"] is True
    assert result["provider"] == provider
    assert result["video"] == f"output/{stem}.mp4"
    assert (project_dir / result["video"]).read_bytes() == b"video+audio"
    assert calls["assemble"]
    assert calls["mux"]


@pytest.mark.parametrize(
    "route",
    [studio_app.render_firefly_assemble, studio_app.render_imagineart_assemble],
)
def test_hosted_assemble_ignores_unconfined_legacy_audio_path(tmp_path, monkeypatch, route):
    store = ProjectStore(tmp_path / "data")
    proj = store.create("Hosted assemble path confinement")
    external_audio = tmp_path / "outside.wav"
    external_audio.write_bytes(b"must not be read")
    proj.meta = {
        "audio_path": str(external_audio),
        "last_plan": {
            "variants": [
                {
                    "name": "v1",
                    "scenes": [{"start_s": 0.0, "end_s": 1.0, "prompt": "safe"}],
                }
            ]
        },
    }
    store.save(proj)
    project_dir = store.project_dir(proj.id)
    stills_dir = project_dir / "stills" / "variant_0"
    stills_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16)).save(stills_dir / "scene_0000.png")

    def fake_assemble_slideshow(*, out_mp4, **_kwargs):
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        out_mp4.write_bytes(b"video")

    def fail_mux(*_args, **_kwargs):
        raise AssertionError("unconfined audio path reached FFmpeg mux")

    monkeypatch.setattr(studio_app, "store", store)
    monkeypatch.setattr(studio_app, "assemble_slideshow", fake_assemble_slideshow)
    monkeypatch.setattr(studio_app, "mux_audio", fail_mux)

    result = route(proj.id, {"variant_index": 0, "fps": 24})

    assert result["ok"] is True
    assert result["video"].endswith("_v0.mp4")
