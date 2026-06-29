"""ImagineArt (Vyro.ai) API client for EDMG Studio.

Supports hosted image generation and async video generation via the public
ImagineArt REST API (https://api.vyro.ai/v2). Configure an API key in
Settings → Tokens → ImagineArt API key, then enable the provider under
Settings → GPU / Render Runtime → ImagineArt.

Auth:
  Set IMAGINEART_API_KEY env var or save ``imagineart_api_key`` in Studio Settings.
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Any

import requests
from PIL import Image, ImageOps

from ..errors import UserFacingError


IMAGINEART_API_BASE = "https://api.vyro.ai/v2"

IMAGINEART_IMAGE_STYLES = (
    "imagine-turbo",
    "realistic",
    "anime",
    "flux-schnell",
    "flux-dev",
    "flux-dev-fast",
    "sdxl-1.0",
)

IMAGINEART_VIDEO_STYLES = (
    "kling-1.0-pro",
    "kling-1.0-standard",
    "kling-1.5",
    "imagine-v2",
    "imagine-v1",
    "hailuo-ai",
    "hailuo-live-ai",
)

IMAGINEART_ASPECT_RATIOS = ("1:1", "3:2", "4:3", "3:4", "16:9", "9:16")



@dataclass(frozen=True)
class ImagineArtImageResult:
    image: Image.Image
    model: str | None
    seed: int | None = None
    generation_id: str | None = None


@dataclass(frozen=True)
class ImagineArtVideoResult:
    video_bytes: bytes
    content_type: str
    model: str | None
    generation_id: str | None = None
    duration_s: float | None = None


def _closest_aspect_ratio(width: int, height: int) -> str:
    target = float(width) / float(max(1, height))

    def _score(r: str) -> float:
        w, h = r.split(":")
        return abs(target - float(w) / float(h))

    return min(IMAGINEART_ASPECT_RATIOS, key=_score)


def _image_to_jpeg_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=92)
    return buf.getvalue()


class ImagineArtClient:
    """ImagineArt image and video generation client."""

    def __init__(self, api_key: str, base_url: str = IMAGINEART_API_BASE) -> None:
        self.api_key = str(api_key or "").strip()
        self.base_url = str(base_url or IMAGINEART_API_BASE).rstrip("/")
        if not self.api_key:
            raise UserFacingError(
                "ImagineArt API key is not configured.",
                hint="Open Settings → Tokens, save your ImagineArt API key, then retry.",
                code="IMAGINEART_API_KEY_MISSING",
                status_code=400,
            )

    def _headers(self, *, accept: str = "application/json") -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": accept,
        }

    def _raise_api_error(self, resp: requests.Response) -> None:
        message = ""
        try:
            data = resp.json()
            if isinstance(data, dict):
                message = str(data.get("message") or data.get("error") or "").strip()
        except Exception:
            message = (resp.text or "").strip()[:500]
        raise UserFacingError(
            message or f"ImagineArt request failed ({resp.status_code}).",
            hint="Check your API key and ImagineArt account balance, then retry.",
            code="IMAGINEART_API_ERROR",
            status_code=max(400, min(resp.status_code, 599)),
        )

    def generate_image(
        self,
        *,
        prompt: str,
        width: int,
        height: int,
        style: str = "imagine-turbo",
        aspect_ratio: str | None = None,
        seed: int | None = None,
        init_image: Image.Image | None = None,
        timeout_s: float = 180.0,
    ) -> ImagineArtImageResult:
        style_l = str(style or "imagine-turbo").strip().lower()
        if style_l not in IMAGINEART_IMAGE_STYLES:
            style_l = "imagine-turbo"
        ratio = str(aspect_ratio or _closest_aspect_ratio(int(width), int(height))).strip()
        if ratio not in IMAGINEART_ASPECT_RATIOS:
            ratio = _closest_aspect_ratio(int(width), int(height))

        files: list[tuple[str, tuple[str, bytes, str] | tuple[None, str]]] = [
            ("prompt", (None, str(prompt or "").strip() or "cinematic music video still")),
            ("style", (None, style_l)),
            ("aspect_ratio", (None, ratio)),
        ]
        if seed is not None:
            files.append(("seed", (None, str(int(seed)))))
        if init_image is not None:
            files.append(("file", ("init.jpg", _image_to_jpeg_bytes(init_image), "image/jpeg")))

        resp = requests.post(
            f"{self.base_url}/image/generations",
            headers=self._headers(accept="*/*"),
            files=files,
            timeout=(30, timeout_s),
        )
        if resp.status_code >= 400:
            self._raise_api_error(resp)

        content_type = str(resp.headers.get("Content-Type") or "").lower()
        if "json" in content_type:
            self._raise_api_error(resp)

        try:
            img = Image.open(io.BytesIO(resp.content))
            img = ImageOps.exif_transpose(img).convert("RGB")
            if img.size != (int(width), int(height)):
                img = ImageOps.fit(img, (int(width), int(height)), method=Image.LANCZOS)
        except Exception as exc:
            raise UserFacingError(
                "ImagineArt returned image data Studio could not decode.",
                hint="Retry the render or choose a different image style.",
                code="IMAGINEART_IMAGE_DECODE_FAILED",
                status_code=502,
            ) from exc

        return ImagineArtImageResult(
            image=img,
            model=style_l,
            seed=int(seed) if seed is not None else None,
        )

    def generate_video(
        self,
        *,
        prompt: str,
        style: str = "kling-1.0-pro",
        init_image: Image.Image | None = None,
        timeout_s: float = 600.0,
        poll_interval_s: float = 5.0,
    ) -> ImagineArtVideoResult:
        style_l = str(style or "kling-1.0-pro").strip().lower()
        if style_l not in IMAGINEART_VIDEO_STYLES:
            style_l = "kling-1.0-pro"

        prompt_s = str(prompt or "").strip() or "cinematic music video clip"
        if init_image is not None:
            endpoint = f"{self.base_url}/video/image-to-video"
            files: list[tuple[str, tuple[str, bytes, str] | tuple[None, str]]] = [
                ("style", (None, style_l)),
                ("prompt", (None, prompt_s)),
                ("file", ("init.jpg", _image_to_jpeg_bytes(init_image), "image/jpeg")),
            ]
        else:
            endpoint = f"{self.base_url}/video/text-to-video"
            files = [
                ("style", (None, style_l)),
                ("prompt", (None, prompt_s)),
            ]

        resp = requests.post(
            endpoint,
            headers=self._headers(),
            files=files,
            timeout=(30, 120),
        )
        if resp.status_code >= 400:
            self._raise_api_error(resp)

        try:
            submit = resp.json()
        except Exception:
            submit = {}
        if not isinstance(submit, dict):
            submit = {}
        job_id = str(submit.get("id") or submit.get("uuid") or "").strip()
        if not job_id:
            raise UserFacingError(
                "ImagineArt did not return a video job id.",
                hint="Retry the render.",
                code="IMAGINEART_VIDEO_NO_JOB",
                status_code=502,
            )

        video_url = self._poll_video_job(
            job_id,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
        )
        video_bytes, content_type = self._download_bytes(video_url)
        return ImagineArtVideoResult(
            video_bytes=video_bytes,
            content_type=content_type or "video/mp4",
            model=style_l,
            generation_id=job_id,
        )

    def _poll_video_job(
        self,
        job_id: str,
        *,
        timeout_s: float,
        poll_interval_s: float,
    ) -> str:
        deadline = time.time() + max(30.0, float(timeout_s))
        delay = max(1.0, float(poll_interval_s))
        status_url = f"{self.base_url}/video/{job_id}/status"
        max_polls = max(3, int(max(30.0, float(timeout_s)) / delay) + 2)

        for _ in range(max_polls):
            resp = requests.get(status_url, headers=self._headers(), timeout=(15, 60))
            if resp.status_code >= 400:
                self._raise_api_error(resp)

            try:
                data = resp.json()
            except Exception:
                data = {}
            if not isinstance(data, dict):
                data = {}
            status = str(data.get("status") or "").strip().lower()
            if status in {"success", "completed"}:
                video_url = self._extract_video_url(data)
                if video_url:
                    return video_url
                raise UserFacingError(
                    "ImagineArt completed the video job but returned no download URL.",
                    hint="Retry the render.",
                    code="IMAGINEART_VIDEO_NO_OUTPUT",
                    status_code=502,
                )
            if status in {"failed", "error", "cancelled"}:
                raise UserFacingError(
                    "ImagineArt video generation failed.",
                    hint="Retry with a different prompt or video style.",
                    code="IMAGINEART_VIDEO_JOB_FAILED",
                    status_code=502,
                )
            if time.time() >= deadline:
                break
            time.sleep(delay)

        raise UserFacingError(
            "ImagineArt video generation timed out.",
            hint="Retry the render or increase the timeout in Settings.",
            code="IMAGINEART_VIDEO_TIMEOUT",
            status_code=504,
        )

    @staticmethod
    def _extract_video_url(data: dict[str, Any]) -> str:
        video = data.get("video") if isinstance(data.get("video"), dict) else {}
        urls = video.get("url") if isinstance(video.get("url"), dict) else {}
        generation = urls.get("generation")
        if isinstance(generation, list) and generation:
            return str(generation[0] or "").strip()
        if isinstance(generation, str) and generation.strip():
            return generation.strip()
        return ""

    def _download_bytes(self, url: str) -> tuple[bytes, str]:
        resp = requests.get(url, timeout=(15, 180))
        resp.raise_for_status()
        return resp.content, str(resp.headers.get("Content-Type") or "video/mp4")
