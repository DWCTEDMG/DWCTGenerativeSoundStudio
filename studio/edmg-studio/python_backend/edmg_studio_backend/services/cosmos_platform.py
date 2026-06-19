"""NVIDIA Cosmos video generation client for DWCT Generative Sound Studio.

Supports:
  - Cosmos-Predict1-7B-Text2World  : text → video
  - Cosmos-Predict1-7B-Video2World : image/video → video (continuation)
  - Cosmos3-Generator              : latest omnimodal model (text/image → video)

Auth:
  Uses the same NVIDIA API key as Nemotron Ultra (nvidia_api_key secret /
  EDMG_AI_NVIDIA_API_KEY env var from build.nvidia.com).  No separate signup.

Cloud endpoint (default):
  https://ai.api.nvidia.com/v1/cosmos/nvidia/{model_name}

Self-hosted NIM:
  Set cosmos_base_url in render settings to your NIM container URL,
  e.g. http://127.0.0.1:8000 — the client will append /v1/infer.

Response:
  The API returns {"b64_video": "<base64-mp4>", ...}.
  The client decodes and saves to disk, returning the path.
"""

from __future__ import annotations

import base64
import io
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from PIL import Image

from ..errors import UserFacingError


# ── Hosted NVIDIA API Catalog endpoints ──────────────────────────────────────
_NVIDIA_COSMOS_BASE = "https://ai.api.nvidia.com/v1/cosmos/nvidia"

COSMOS_MODELS: dict[str, str] = {
    "text2world":  "cosmos-predict1-7b-text2world",
    "video2world": "cosmos-predict1-7b-video2world",
    "cosmos3":     "cosmos3-generator",
}

# Resolutions supported by Cosmos-Predict1 (width x height)
COSMOS_RESOLUTIONS = (
    (1280, 704),
    (704, 1280),
    (960, 544),
    (544, 960),
    (640, 640),
)


@dataclass
class CosmosVideoResult:
    video_path: Path
    model: str
    duration_s: float
    frames: int
    fps: float
    width: int
    height: int
    seed: int | None = None


def _closest_resolution(width: int, height: int) -> tuple[int, int]:
    target_ratio = width / max(1, height)
    best = min(
        COSMOS_RESOLUTIONS,
        key=lambda wh: abs((wh[0] / wh[1]) - target_ratio),
    )
    return best


def _image_to_b64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=92)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class CosmosClient:
    """NVIDIA Cosmos video generation client.

    Works with both the NVIDIA API Catalog (cloud, default) and self-hosted
    NIM containers. Auth is the same nvapi-... key used for Nemotron.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "",
        timeout_s: float = 600.0,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self._custom_base = str(base_url or "").rstrip("/")
        self.timeout_s = float(timeout_s)
        if not self.api_key:
            raise UserFacingError(
                "NVIDIA API key not configured for Cosmos.",
                hint=(
                    "Your existing NVIDIA API key works for Cosmos. "
                    "Go to Settings → AI Provider and verify the NVIDIA API key is saved."
                ),
                code="COSMOS_API_KEY_MISSING",
                status_code=400,
            )

    def _endpoint(self, model_slug: str) -> str:
        if self._custom_base:
            return f"{self._custom_base}/v1/infer"
        return f"{_NVIDIA_COSMOS_BASE}/{model_slug}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── Text-to-video ─────────────────────────────────────────────────────────

    def text_to_video(
        self,
        *,
        prompt: str,
        out_path: Path,
        negative_prompt: str = "blurry, low quality, text, watermark, logo",
        width: int = 1280,
        height: int = 704,
        fps: float = 24.0,
        num_frames: int = 121,
        steps: int = 50,
        guidance_scale: float = 7.5,
        seed: int | None = None,
        prompt_upsampling: bool = True,
        model: str = "text2world",
    ) -> CosmosVideoResult:
        """Generate a video clip from a text prompt using Cosmos."""
        slug = COSMOS_MODELS.get(model, COSMOS_MODELS["text2world"])
        res_w, res_h = _closest_resolution(width, height)

        body: dict[str, Any] = {
            "prompt": str(prompt or "cinematic music video").strip(),
            "negative_prompt": str(negative_prompt or "").strip(),
            "prompt_upsampling": bool(prompt_upsampling),
            "guidance_scale": max(1.0, min(20.0, float(guidance_scale))),
            "steps": max(10, min(100, int(steps))),
            "video_params": {
                "height": res_h,
                "width": res_w,
                "frames_count": max(25, int(num_frames)),
                "frames_per_sec": float(fps),
            },
        }
        if seed is not None:
            body["seed"] = int(seed)

        return self._call_and_save(slug, body, out_path, model=slug, fps=fps,
                                   width=res_w, height=res_h)

    # ── Image-to-video ────────────────────────────────────────────────────────

    def image_to_video(
        self,
        *,
        image: Image.Image,
        out_path: Path,
        prompt: str = "",
        negative_prompt: str = "blurry, low quality, text, watermark, logo",
        width: int = 1280,
        height: int = 704,
        fps: float = 24.0,
        num_frames: int = 121,
        steps: int = 50,
        guidance_scale: float = 7.5,
        seed: int | None = None,
        model: str = "video2world",
    ) -> CosmosVideoResult:
        """Generate video continuation from a still image (Cosmos Video2World)."""
        slug = COSMOS_MODELS.get(model, COSMOS_MODELS["video2world"])
        res_w, res_h = _closest_resolution(width, height)
        img_b64 = _image_to_b64(image)

        body: dict[str, Any] = {
            "image": f"data:image/jpeg;base64,{img_b64}",
            "guidance_scale": max(1.0, min(20.0, float(guidance_scale))),
            "steps": max(10, min(100, int(steps))),
            "video_params": {
                "height": res_h,
                "width": res_w,
                "frames_count": max(25, int(num_frames)),
                "frames_per_sec": float(fps),
            },
        }
        if prompt:
            body["prompt"] = str(prompt).strip()
        if negative_prompt:
            body["negative_prompt"] = str(negative_prompt).strip()
        if seed is not None:
            body["seed"] = int(seed)

        return self._call_and_save(slug, body, out_path, model=slug, fps=fps,
                                   width=res_w, height=res_h)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _call_and_save(
        self,
        model_slug: str,
        body: dict[str, Any],
        out_path: Path,
        *,
        model: str,
        fps: float,
        width: int,
        height: int,
    ) -> CosmosVideoResult:
        endpoint = self._endpoint(model_slug)
        try:
            resp = requests.post(
                endpoint,
                headers=self._headers(),
                json=body,
                timeout=(30, self.timeout_s),
            )
        except requests.exceptions.Timeout:
            raise UserFacingError(
                "Cosmos video generation timed out.",
                hint=(
                    "Cosmos generation takes 3–10 minutes for a 5-second clip. "
                    "Increase the timeout in Settings → GPU / Render Runtime → Cosmos, or reduce steps/frames."
                ),
                code="COSMOS_TIMEOUT",
                status_code=504,
            )

        if resp.status_code >= 400:
            self._raise_api_error(resp)

        data = resp.json()
        b64_video = str(data.get("b64_video") or data.get("video") or "")
        if not b64_video:
            raise UserFacingError(
                "Cosmos returned a response with no video data.",
                hint="Retry the render. If it keeps failing, check your API quota at build.nvidia.com.",
                code="COSMOS_NO_VIDEO",
                status_code=502,
            )

        video_bytes = base64.b64decode(b64_video)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(video_bytes)

        frames = int(body.get("video_params", {}).get("frames_count") or
                     body.get("num_output_frames") or 121)
        duration_s = frames / max(1.0, fps)
        seed_out = data.get("seed") or body.get("seed")

        return CosmosVideoResult(
            video_path=out_path,
            model=model,
            duration_s=duration_s,
            frames=frames,
            fps=fps,
            width=width,
            height=height,
            seed=int(seed_out) if seed_out is not None else None,
        )

    def _raise_api_error(self, response: requests.Response) -> None:
        message = f"NVIDIA Cosmos request failed ({response.status_code})."
        hint = "Check your NVIDIA API key and quota at build.nvidia.com, then retry."
        try:
            payload = response.json()
            detail = (
                payload.get("detail")
                or payload.get("message")
                or (payload.get("errors") or [""])[0]
                or ""
            )
            if detail:
                message = f"Cosmos error: {detail}"
            if response.status_code in (401, 403):
                hint = (
                    "Your NVIDIA API key was rejected. Verify it in Settings → AI Provider → NVIDIA API key. "
                    "The same key used for Nemotron works for Cosmos."
                )
            elif response.status_code == 429:
                hint = "NVIDIA API rate limit hit. Wait a moment, then retry."
            elif response.status_code == 402:
                hint = "NVIDIA API quota exceeded. Check your plan at build.nvidia.com."
        except Exception:
            pass
        raise UserFacingError(
            message,
            hint=hint,
            code="COSMOS_API_ERROR",
            status_code=502 if response.status_code < 500 else response.status_code,
        )
