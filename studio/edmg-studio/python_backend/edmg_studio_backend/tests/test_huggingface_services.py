import base64
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from edmg_studio_backend.api import huggingface_services as module


class Secrets:
    def __init__(self):
        self.values = {}

    def get(self, name):
        return self.values.get(name, "")

    def set(self, name, value):
        self.values[name] = value


class Response:
    def __init__(self, body=None, status=200, headers=None, lines=None):
        self.body, self.status_code = body, status
        self.headers = headers or {"content-type": "application/json"}
        self.lines = lines or []

    def json(self):
        return self.body

    def iter_lines(self, **kwargs):
        return iter(self.lines)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    secrets = Secrets()
    app = FastAPI()
    app.include_router(module.create_huggingface_services_router(tmp_path, secrets))
    monkeypatch.setattr(module, "hf_token_candidates", lambda **kwargs:
        [SimpleNamespace(token="test-hf-token")])
    return TestClient(app), secrets, tmp_path


def test_settings_keep_credentials_out_of_response_and_disk(fixture):
    client, secrets, root = fixture
    response = client.post("/v1/huggingface/settings", json={
        "hf_token": "private-hf-token", "webhook_secret": "private-hook-secret"})
    assert response.status_code == 200
    assert response.json()["has_webhook_secret"] is True
    assert secrets.get("hf_token") == "private-hf-token"
    saved = (root / "config/huggingface_services.json").read_text()
    assert "private-" not in saved + response.text
    client.post("/v1/huggingface/settings", json={})
    assert secrets.get("hf_token") == "private-hf-token"


@pytest.mark.parametrize("url", ["http://localhost/v1", "https://evil.example/v1",
    "https://a.endpoints.huggingface.cloud.evil.example/v1", "https://user:pass@a.endpoints.huggingface.cloud"])
def test_credentials_cannot_be_routed_to_non_hf_servers(fixture, url):
    client, _, _ = fixture
    assert client.post("/v1/huggingface/settings", json={"nemotron_endpoint": url}).status_code == 422


def test_webhook_requires_receiver_and_secret(fixture, monkeypatch):
    client, _, _ = fixture
    monkeypatch.setattr(module.requests, "request", lambda *args, **kwargs: pytest.fail("must not contact HF"))
    assert client.post("/v1/huggingface/webhook").status_code == 422


def test_webhook_update_reuses_id_and_never_returns_secret(fixture, monkeypatch):
    client, secrets, _ = fixture
    client.post("/v1/huggingface/settings", json={"webhook_url": "https://receiver.example/hook",
        "webhook_secret": "secret-hook"})
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return Response({"webhook": {"id": "hook123", "secret": "secret-hook"}})

    monkeypatch.setattr(module.requests, "request", request)
    first = client.post("/v1/huggingface/webhook")
    second = client.post("/v1/huggingface/webhook")
    assert first.status_code == second.status_code == 200
    assert "secret-hook" not in first.text + second.text
    assert calls[0][0] == calls[1][0] == "POST"
    assert calls[1][1].endswith("/hook123")
    assert calls[0][2]["json"]["domains"] == ["repo"]
    assert len(calls[0][2]["json"]["watched"]) == 3
    assert calls[0][2]["allow_redirects"] is False
    # Reopening Settings and saving blank credentials must not lose registration.
    client.post("/v1/huggingface/settings", json={"webhook_url": "https://receiver.example/hook"})
    assert client.get("/v1/huggingface/settings").json()["webhook_id"] == "hook123"


def test_director_uses_saved_hf_credential_only_for_hf_hosts(monkeypatch, tmp_path):
    from edmg_studio_backend.services import director_providers, secrets
    monkeypatch.delenv("EDMG_NEMOTRON_API_KEY", raising=False)
    monkeypatch.setenv("HF_TOKEN", "stale-environment-token")
    saved = Secrets()
    saved.set("hf_token", "saved-hf-token")
    monkeypatch.setattr(secrets, "SecretStore", lambda *args, **kwargs: saved)
    settings = {"primary_endpoint": "https://a.endpoints.huggingface.cloud/v1", "primary_server_model": "nemotron"}
    assert director_providers._server_endpoint(settings, "primary").api_key == "saved-hf-token"
    settings["primary_endpoint"] = "https://other.example/v1"
    assert director_providers._server_endpoint(settings, "primary").api_key == ""


def test_mcp_discovers_tools_using_negotiated_session_and_sse(fixture, monkeypatch):
    client, _, _ = fixture
    calls = []

    def request(method, url, **kwargs):
        body = kwargs["json"]
        calls.append((url, kwargs))
        if body["method"] == "initialize":
            return Response({"id": 1, "result": {"protocolVersion": "2025-03-26"}},
                headers={"content-type": "application/json", "Mcp-Session-Id": "session123"})
        if body["method"] == "notifications/initialized":
            return Response(status=202)
        return Response(headers={"content-type": "text/event-stream"}, lines=[
            'data: {"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"generate"}]}}'])

    monkeypatch.setattr(module.requests, "request", request)
    response = client.get("/v1/huggingface/mcp/hunyuan/tools")
    assert response.status_code == 200
    assert response.json()["tools"] == [{"name": "generate"}]
    assert response.json()["inference_verified"] is False
    assert calls[2][1]["headers"]["Mcp-Session-Id"] == "session123"
    assert client.get("/v1/huggingface/mcp/arbitrary/tools").status_code == 404


def test_credential_fallback_and_paused_errors_are_safe(fixture, monkeypatch):
    client, _, _ = fixture
    monkeypatch.setattr(module, "hf_token_candidates", lambda **kwargs:
        [SimpleNamespace(token="bad"), SimpleNamespace(token="good")])
    calls = []

    def request(method, url, **kwargs):
        calls.append(kwargs["headers"]["Authorization"])
        return Response(status=401 if len(calls) == 1 else 503)

    monkeypatch.setattr(module.requests, "request", request)
    response = client.post("/v1/huggingface/hunyuan/preview", json={"prompt": "test"})
    assert response.status_code == 503
    assert calls == ["Bearer bad", "Bearer good"]
    assert "paused" in response.text
    assert "Bearer" not in response.text


def test_preview_validates_mp4_and_actual_metadata(fixture, monkeypatch):
    client, _, _ = fixture
    video = base64.b64encode(b"\x00\x00\x00\x18ftypisom0000").decode()
    payload = {"video_base64": video, "frames": 17, "fps": 24, "model": "hunyuan"}
    monkeypatch.setattr(module.requests, "request", lambda *args, **kwargs: Response(payload))
    assert client.post("/v1/huggingface/hunyuan/preview", json={"prompt": "test"}).status_code == 200
    payload["video_base64"] = base64.b64encode(b"not video data").decode()
    assert client.post("/v1/huggingface/hunyuan/preview", json={"prompt": "test"}).status_code == 502
    assert client.post("/v1/huggingface/hunyuan/preview", json={"prompt": "test", "frames": 100}).status_code == 422


def test_non_ascii_secret_is_rejected(fixture):
    client, _, _ = fixture
    assert client.post("/v1/huggingface/settings", json={"webhook_secret": "\u00e9"}).status_code == 422
