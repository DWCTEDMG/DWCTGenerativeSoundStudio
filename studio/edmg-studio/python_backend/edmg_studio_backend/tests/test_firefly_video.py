from __future__ import annotations

import pytest

from edmg_studio_backend.services import firefly_platform as fp
from edmg_studio_backend.services.firefly_platform import FireflyClient
from edmg_studio_backend.services.render_settings import (
    VIDEO_GENERATION_PREFERENCES,
    RenderSettingsStore,
)


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
    """Routes Firefly HTTP calls by URL and scripts the async poll sequence."""

    def __init__(self):
        self.poll_calls = 0
        self.posted_bodies = []

    def post(self, url, **kwargs):
        if "token" in url:
            return _FakeResp(200, {"access_token": "tok", "expires_in": 3600})
        if "/storage/image" in url:
            return _FakeResp(200, {"images": [{"id": "asset-123"}]})
        if "/videos/generate" in url:
            self.posted_bodies.append(kwargs.get("json") or {})
            return _FakeResp(
                202,
                {"jobId": "job-1", "statusUrl": "https://firefly-api.adobe.io/v3/status/job-1"},
                content=b"x",
            )
        raise AssertionError(f"unexpected POST {url}")

    def get(self, url, **kwargs):
        if "/status/" in url:
            self.poll_calls += 1
            if self.poll_calls < 2:
                return _FakeResp(200, {"status": "running"}, content=b"x")
            return _FakeResp(
                200,
                {
                    "status": "succeeded",
                    "outputs": [{"video": {"url": "https://cdn.example/clip.mp4"}, "seed": 42}],
                },
                content=b"x",
            )
        if url.endswith(".mp4"):
            return _FakeResp(200, content=b"MP4DATA", headers={"Content-Type": "video/mp4"})
        raise AssertionError(f"unexpected GET {url}")


@pytest.fixture(autouse=True)
def _reset_token_and_sleep(monkeypatch):
    monkeypatch.setattr(fp, "_token_cache", fp._TokenCache())
    monkeypatch.setattr(fp.time, "sleep", lambda *_a, **_k: None)


def test_generate_video_text_to_video(monkeypatch):
    fake = _FakeRequests()
    monkeypatch.setattr(fp, "requests", fake)

    client = FireflyClient(client_id="cid", client_secret="secret")
    result = client.generate_video(
        prompt="neon city at night",
        width=1280,
        height=720,
        duration_s=5,
        poll_interval_s=0.0,
    )

    assert result.video_bytes == b"MP4DATA"
    assert result.content_type == "video/mp4"
    assert result.model == "firefly-video"
    assert result.seed == 42
    assert result.generation_id == "job-1"
    assert result.duration_s == 5.0
    assert fake.poll_calls >= 2  # polled until succeeded

    body = fake.posted_bodies[0]
    assert body["prompt"] == "neon city at night"
    assert body["sizes"] == [{"width": 1280, "height": 720}]
    assert body["videoSettings"]["durationInSeconds"] == 5


def test_generate_video_clamps_duration(monkeypatch):
    fake = _FakeRequests()
    monkeypatch.setattr(fp, "requests", fake)
    client = FireflyClient(client_id="cid", client_secret="secret")
    client.generate_video(prompt="x", width=1080, height=1920, duration_s=999, poll_interval_s=0.0)
    assert fake.posted_bodies[0]["videoSettings"]["durationInSeconds"] == fp.FIREFLY_VIDEO_MAX_SECONDS
    # portrait request maps to a portrait Firefly size
    assert fake.posted_bodies[0]["sizes"][0]["height"] >= fake.posted_bodies[0]["sizes"][0]["width"]


def test_generate_video_job_failure(monkeypatch):
    fake = _FakeRequests()

    def _get(url, **kwargs):
        if "/status/" in url:
            return _FakeResp(200, {"status": "failed"}, content=b"x")
        raise AssertionError(url)

    fake.get = _get  # type: ignore[assignment]
    monkeypatch.setattr(fp, "requests", fake)
    client = FireflyClient(client_id="cid", client_secret="secret")
    with pytest.raises(fp.UserFacingError) as exc:
        client.generate_video(prompt="x", width=1280, height=720, poll_interval_s=0.0)
    assert exc.value.code == "FIREFLY_VIDEO_JOB_FAILED"


def test_missing_credentials_raises():
    with pytest.raises(fp.UserFacingError) as exc:
        FireflyClient(client_id="", client_secret="")
    assert exc.value.code == "FIREFLY_CREDENTIALS_MISSING"


def test_render_settings_exposes_firefly_video(tmp_path):
    assert "firefly_cloud" in VIDEO_GENERATION_PREFERENCES
    store = RenderSettingsStore(tmp_path)
    saved = store.update({"firefly": {"video_enabled": True, "video_duration_s": 99}})
    assert saved["firefly"]["video_enabled"] is True
    # duration clamped to the 1..10 range
    assert saved["firefly"]["video_duration_s"] == 10
