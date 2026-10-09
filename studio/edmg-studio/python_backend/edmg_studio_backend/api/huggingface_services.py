"""Hosted HF connections for the native Studio; no local model downloads."""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..services.hf_auth import hf_token_candidates


class HostedSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    namespace: str = "gulle1155"
    nemotron_endpoint: str = "https://6ac87f4453d27c9b5cb0cba8.endpoints.huggingface.cloud/v1"
    hunyuan_endpoint: str = "https://6ac883da53d27c9b5cb0cbf7.endpoints.huggingface.cloud"
    webhook_url: str = ""
    webhook_id: str = ""

    @field_validator("namespace")
    @classmethod
    def namespace_valid(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", value):
            raise ValueError("Enter a Hugging Face username or organization")
        return value

    @field_validator("nemotron_endpoint", "hunyuan_endpoint")
    @classmethod
    def endpoint_valid(cls, value):
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname
                or not parsed.hostname.endswith(".endpoints.huggingface.cloud")
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.port not in (None, 443)):
            raise ValueError("Use an HTTPS Hugging Face dedicated endpoint URL")
        return value.rstrip("/")

    @field_validator("webhook_url")
    @classmethod
    def callback_valid(cls, value):
        if value:
            parsed = urlsplit(value)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise ValueError("Webhook receiver must be an HTTPS URL without embedded credentials")
        return value


class SaveHostedSettings(HostedSettings):
    hf_token: str = Field(default="", max_length=1024, repr=False)
    webhook_secret: str = Field(default="", max_length=256, repr=False)


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=4000)
    seed: int = Field(default=42, ge=0, le=2147483647)
    frames: int = Field(default=17)
    steps: int = Field(default=20, ge=1, le=50)

    @field_validator("frames")
    @classmethod
    def frames_valid(cls, value):
        if value not in (9, 17, 25, 33):
            raise ValueError("Preview frames must be 9, 17, 25, or 33")
        return value


def _rpc_result(response, request_id):
    """Read one JSON-RPC reply, supporting JSON and Streamable HTTP SSE."""
    if "application/json" in response.headers.get("content-type", ""):
        payload = response.json()
    else:
        payload = None
        for line in response.iter_lines(decode_unicode=True):
            if line and line.startswith("data:"):
                item = json.loads(line[5:].strip())
                if item.get("id") == request_id:
                    payload = item
                    break
        if payload is None:
            raise HTTPException(502, "MCP server returned no matching response")
    if not isinstance(payload, dict) or payload.get("id") != request_id or "error" in payload:
        raise HTTPException(502, "MCP server rejected tool discovery")
    return payload.get("result", {})


def create_huggingface_services_router(data_dir: Path, secrets_store):
    router = APIRouter(prefix="/v1/huggingface", tags=["huggingface"])
    path = Path(data_dir) / "config" / "huggingface_services.json"

    def load():
        return HostedSettings.model_validate_json(path.read_text()) if path.exists() else HostedSettings()

    def persist(settings):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)

    def response_json(response):
        try:
            return response.json()
        except ValueError:
            raise HTTPException(502, "Hugging Face returned invalid JSON") from None

    def request(method, url, **kwargs):
        # URLs originate only from validated HF settings or fixed Hub routes.
        candidates = hf_token_candidates(secrets_store=secrets_store)
        # Private Spaces mask rejected credentials as 404, so use the credential
        # explicitly saved for this connection before inherited environment tokens.
        saved_token = secrets_store.get("hf_token")
        candidates.sort(key=lambda candidate: candidate.token != saved_token)
        if not candidates:
            raise HTTPException(401, "Save a Hugging Face token or sign in with hf auth login")
        headers = kwargs.pop("headers", {})
        for candidate in candidates:
            try:
                response = requests.request(method, url, headers={**headers,
                    "Authorization": f"Bearer {candidate.token}"}, allow_redirects=False, **kwargs)
            except requests.RequestException:
                raise HTTPException(502, "Hugging Face could not be reached; retry later") from None
            if response.status_code == 401:
                response.close()
                continue
            if not 200 <= response.status_code < 300:
                status = response.status_code
                response.close()
                if status == 503:
                    raise HTTPException(503, "Service is paused, starting, or busy. Check its Hugging Face dashboard and retry.")
                raise HTTPException(status if status in (403, 404, 429) else 502,
                                    f"Hugging Face request failed (HTTP {status})")
            return response
        raise HTTPException(401, "Hugging Face rejected the available tokens; update the token in Settings")

    @router.get("/settings")
    def get_settings():
        settings = load()
        namespace = settings.namespace
        return {**settings.model_dump(), "has_token": bool(hf_token_candidates(secrets_store=secrets_store)),
            "has_webhook_secret": bool(secrets_store.get("hf_webhook_secret")),
            "mcp_servers": {
                "hub": "https://huggingface.co/mcp",
                "hunyuan": f"https://{namespace}-hunyuan-video-1-5-zerogpu.hf.space/gradio_api/mcp/",
                "nemotron": f"https://{namespace}-nemotron-3-nano-omni-zerogpu.hf.space/gradio_api/mcp/"}}

    @router.post("/settings")
    def save_settings(payload: SaveHostedSettings):
        previous = load()
        if payload.hf_token.strip():
            secrets_store.set("hf_token", payload.hf_token.strip())
        if payload.webhook_secret:
            if not payload.webhook_secret.isascii():
                raise HTTPException(422, "Webhook secret must contain ASCII characters")
            secrets_store.set("hf_webhook_secret", payload.webhook_secret)
        saved = HostedSettings.model_validate(payload.model_dump(exclude={"hf_token", "webhook_secret"}))
        if not saved.webhook_id and saved.namespace == previous.namespace:
            saved = saved.model_copy(update={"webhook_id": previous.webhook_id})
        persist(saved)
        return get_settings()

    @router.get("/mcp/{server}/tools")
    def discover_tools(server: str):
        urls = get_settings()["mcp_servers"]
        if server not in urls:
            raise HTTPException(404, "Unknown Studio MCP connection")
        url = urls[server]
        headers = {"Accept": "application/json, text/event-stream"}
        with request("POST", url, headers=headers, json={"jsonrpc": "2.0", "id": 1,
                "method": "initialize", "params": {"protocolVersion": "2025-03-26",
                    "capabilities": {}, "clientInfo": {"name": "EDMG Studio", "version": "1.2.0"}}},
                stream=True, timeout=30) as response:
            initialized = _rpc_result(response, 1)
            session = response.headers.get("Mcp-Session-Id")
        headers["MCP-Protocol-Version"] = initialized.get("protocolVersion", "2025-03-26")
        if session:
            headers["Mcp-Session-Id"] = session
        with request("POST", url, headers=headers, json={"jsonrpc": "2.0",
                     "method": "notifications/initialized"}, timeout=30):
            pass
        with request("POST", url, headers=headers, json={"jsonrpc": "2.0", "id": 2,
                     "method": "tools/list"}, stream=True, timeout=30) as response:
            result = _rpc_result(response, 2)
        return {"server": server, "url": url, "tools": result.get("tools", []),
                "next_cursor": result.get("nextCursor"), "inference_verified": False}

    @router.post("/webhook")
    def register_webhook():
        settings = load()
        secret = secrets_store.get("hf_webhook_secret")
        if not settings.webhook_url or not secret:
            raise HTTPException(422, "Save a receiving HTTPS URL and webhook secret first")
        watched = [{"type": "space", "name": f"{settings.namespace}/{name}"} for name in
            ("hunyuan-video-1-5-zerogpu", "nemotron-3-nano-omni-zerogpu")]
        watched.append({"type": "model", "name": f"{settings.namespace}/studio-hunyuan-video-1-5-endpoint"})
        method = "POST"
        if settings.webhook_id and not re.fullmatch(r"[a-zA-Z0-9_-]+", settings.webhook_id):
            raise HTTPException(422, "Invalid webhook ID")
        url = "https://huggingface.co/api/settings/webhooks" + ("/" + settings.webhook_id if settings.webhook_id else "")
        with request(method, url, json={"watched": watched, "url": settings.webhook_url,
                "domains": ["repo"], "secret": secret}, timeout=30) as response:
            result = response_json(response)
        identifier = result.get("webhook", result).get("id")
        if not identifier:
            raise HTTPException(502, "Hugging Face did not return a webhook ID")
        persist(settings.model_copy(update={"webhook_id": identifier}))
        return {"id": identifier, "url": settings.webhook_url, "domains": ["repo"], "watched": watched}

    @router.post("/hunyuan/preview")
    def preview(payload: PreviewRequest):
        with request("POST", load().hunyuan_endpoint, json={"inputs": payload.prompt,
                "parameters": {"seed": payload.seed, "num_frames": payload.frames,
                    "num_inference_steps": payload.steps}}, timeout=600) as response:
            result = response_json(response)
        if isinstance(result, list):
            result = result[0]
        encoded = result.get("video_base64", "")
        if len(encoded) > 64 * 1024 * 1024:
            raise HTTPException(502, "Preview exceeded the 48 MB limit")
        try:
            video = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise HTTPException(502, "Endpoint returned invalid video data") from None
        if len(video) < 12 or video[4:8] != b"ftyp":
            raise HTTPException(502, "Endpoint did not return an MP4")
        if result.get("frames") != payload.frames or result.get("fps") != 24:
            raise HTTPException(502, "Endpoint returned unexpected preview frame count or frame rate")
        return {key: result[key] for key in ("video_base64", "frames", "fps", "model",
            "device", "elapsed_seconds") if key in result}

    return router
