from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest
from PIL import Image

from edmg_studio_backend.errors import UserFacingError
from edmg_studio_backend.services import azure_foundry_platform as platform
from edmg_studio_backend.services.azure_foundry_platform import AzureFoundryClient, validate_azure_url
from edmg_studio_backend.services.render_settings import RenderSettingsStore

RESOURCE = "https://dwctpart.services.ai.azure.com"
VIDEO = RESOURCE + "/openai/v1/videos/sync"


def client(**kwargs):
    return AzureFoundryClient(api_key="test-secret", endpoint_url=RESOURCE,
                              deployment_name="nvidia--cosmos3-super", video_endpoint_url=VIDEO, **kwargs)


@pytest.mark.parametrize("url", ["http://dwctpart.services.ai.azure.com", "https://evil.example",
    "https://dwctpart.services.ai.azure.com.evil.example", "https://test-secret@dwctpart.services.ai.azure.com",
    RESOURCE + "?key=test-secret", RESOURCE + "#key"])
def test_rejects_unsafe_credential_targets(url):
    with pytest.raises(UserFacingError):
        validate_azure_url(url)


def test_requires_explicit_video_endpoint_and_rejects_chat():
    with pytest.raises(UserFacingError, match="not configured"):
        AzureFoundryClient(endpoint_url=RESOURCE, deployment_name="model")._endpoint()
    with pytest.raises(UserFacingError, match="Chat completions"):
        AzureFoundryClient(endpoint_url=RESOURCE, video_endpoint_url=RESOURCE + "/openai/v1/chat/completions")
    with pytest.raises(UserFacingError, match="same Azure resource"):
        AzureFoundryClient(endpoint_url=RESOURCE, video_endpoint_url="https://other.services.ai.azure.com/v1/videos/sync")


def test_connection_is_not_video_qualification(monkeypatch):
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=200, json=lambda: {"data": [{"id": "nvidia--cosmos3-super"}]})
    monkeypatch.setattr(platform.requests, "get", get)
    result = client().check_connection()
    assert result["connected"] and result["deployment_listed"]
    assert result["video_verified"] is False
    assert calls[0][0] == RESOURCE + "/openai/v1/models"
    assert calls[0][1]["allow_redirects"] is False


class Response:
    status_code = 200
    headers = {"Content-Type": "video/mp4"}
    def __init__(self, content=b"invalid"):
        self.content = content
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def iter_content(self, size):
        yield self.content


def mock_tools(monkeypatch):
    monkeypatch.setattr(platform, "ensure_ffmpeg", lambda _: "ffmpeg")
    monkeypatch.setattr(platform, "ensure_ffprobe", lambda _: "ffprobe")


def test_form_contract_image_reference_and_actual_metadata(tmp_path, monkeypatch):
    mock_tools(monkeypatch)
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response(b"validated-mp4")
    monkeypatch.setattr(platform.requests, "post", post)
    monkeypatch.setattr(AzureFoundryClient, "_validate_video", staticmethod(
        lambda *args: {"width": 1280, "height": 720, "frames": 121, "fps": 24, "duration_s": 121 / 24}))
    result = client().image_to_video(image=Image.new("RGB", (8, 8)), prompt="moving ocean", out_path=tmp_path / "video.mp4")
    url, request = calls[0]
    assert url == VIDEO and request["allow_redirects"] is False
    assert "json" not in request and request["data"]["num_frames"] == "121"
    assert request["data"]["model"] == "nvidia--cosmos3-super"
    assert request["files"]["input_reference"][2] == "image/png"
    assert result.video_path.read_bytes() == b"validated-mp4"
    assert result.frames == 121 and result.duration_s == 121 / 24


def test_failed_validation_preserves_existing_output_and_cleans_download(tmp_path, monkeypatch):
    mock_tools(monkeypatch)
    monkeypatch.setattr(platform.requests, "post", lambda *args, **kwargs: Response())
    def invalid(*args):
        raise ValueError("invalid")
    monkeypatch.setattr(AzureFoundryClient, "_validate_video", staticmethod(invalid))
    output = tmp_path / "video.mp4"
    output.write_bytes(b"previous-valid-video")
    with pytest.raises(UserFacingError, match="media validation"):
        client().text_to_video(prompt="ocean", out_path=output)
    assert output.read_bytes() == b"previous-valid-video"
    assert list(tmp_path.iterdir()) == [output]


def test_rejects_successful_chat_response(tmp_path, monkeypatch):
    mock_tools(monkeypatch)
    response = Response()
    response.headers = {"Content-Type": "application/json"}
    monkeypatch.setattr(platform.requests, "post", lambda *args, **kwargs: response)
    with pytest.raises(UserFacingError, match="no MP4"):
        client().text_to_video(prompt="ocean", out_path=tmp_path / "video.mp4")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("status", [302, 401, 403, 404, 422, 429, 503])
def test_errors_do_not_expose_provider_body_or_credentials(status):
    response = SimpleNamespace(status_code=status, json=lambda: {"error": {"message": "test-secret"}})
    with pytest.raises(UserFacingError) as raised:
        client()._raise_api_error(response)
    assert "test-secret" not in str(raised.value)


def test_settings_persist_optional_route_without_changing_local_preferences(tmp_path):
    store = RenderSettingsStore(tmp_path)
    before = store.get()
    saved = store.update({"azure_foundry": {"enabled": True, "endpoint_url": RESOURCE,
        "deployment_name": "nvidia--cosmos3-super", "video_endpoint_url": VIDEO}})
    assert saved["video"] == before["video"]
    assert saved["azure_foundry"]["allow_auto_fallback"] is False
    assert store.get()["azure_foundry"]["video_endpoint_url"] == VIDEO


def test_settings_reject_chat_as_video_before_saving(tmp_path):
    store = RenderSettingsStore(tmp_path)
    with pytest.raises(UserFacingError, match="Chat completions"):
        store.update({"azure_foundry": {"endpoint_url": RESOURCE,
            "video_endpoint_url": RESOURCE + "/openai/v1/chat/completions"}})
    assert store.get()["azure_foundry"]["video_endpoint_url"] == ""


def test_real_decode_and_metadata_validation(tmp_path):
    ffmpeg = platform.ensure_ffmpeg("ffmpeg")
    ffprobe = platform.ensure_ffprobe("ffmpeg")
    path = tmp_path / "clip.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=size=64x64:rate=24",
                    "-frames:v", "25", "-c:v", "libx264", "-y", str(path)], check=True, timeout=30)
    actual = AzureFoundryClient._validate_video(path, ffmpeg, ffprobe, 64, 64, 25, 24)
    assert actual["frames"] == 25
    with pytest.raises(ValueError):
        AzureFoundryClient._validate_video(path, ffmpeg, ffprobe, 64, 64, 121, 24)
