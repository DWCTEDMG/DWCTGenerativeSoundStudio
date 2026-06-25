"""Adobe Firefly API client for DWCT Generative Sound Studio.

Supports:
  - Standard Firefly image generation (text-to-image, image-to-image)
  - Firefly video generation (text-to-video, image-to-video) via the async
    Firefly Video API (submit job -> poll status -> download MP4)
  - Custom model generation (pass custom_model_id from your Firefly fine-tune)
  - OAuth 2.0 token exchange (client_credentials flow via Adobe IMS)

Auth:
  Set ADOBE_CLIENT_ID + ADOBE_CLIENT_SECRET env vars, OR save them as
  adobe_client_id / adobe_client_secret secrets in Studio Settings.
  Access tokens are cached for their lifetime (~24 h) so you won't hit
  the IMS endpoint on every render.

Custom model:
  After training a Firefly Custom Model in Adobe's enterprise portal, copy
  the custom model ID (e.g. "urn:firefly:...") into Settings → Adobe Firefly →
  Custom Model ID field. Leave blank to use the standard Firefly model.
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass, field
from typing import Any

import requests
from PIL import Image, ImageOps

from ..errors import UserFacingError


FIREFLY_API_BASE = "https://firefly-api.adobe.io"
ADOBE_IMS_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
FIREFLY_SCOPE = "openid,AdobeID,firefly_enterprise,firefly_api,ff_apis"

# Firefly v3 supports these content classes
CONTENT_CLASSES = ("photo", "art")

# Aspect ratios supported by Firefly image generation
FIREFLY_ASPECT_RATIOS = (
    "1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "4:5", "5:4",
)

FIREFLY_STYLES = (
    "none", "photo", "art", "graphic", "illustration",
    "sketch", "watercolor", "pixel-art",
)

# Firefly Video supported output sizes (width x height).
FIREFLY_VIDEO_SIZES = (
    (1920, 1080), (1280, 720), (1080, 1920), (720, 1280), (960, 960),
)
# Firefly Video clip length bounds (seconds).
FIREFLY_VIDEO_MIN_SECONDS = 1
FIREFLY_VIDEO_MAX_SECONDS = 10


@dataclass(frozen=True)
class FireflyImageResult:
    image: Image.Image
    model: str | None
    custom_model_id: str | None = None
    seed: int | None = None
    generation_id: str | None = None


@dataclass(frozen=True)
class FireflyVideoResult:
    video_bytes: bytes
    content_type: str
    model: str | None
    seed: int | None = None
    generation_id: str | None = None
    duration_s: float | None = None


def _closest_video_size(width: int, height: int) -> tuple[int, int]:
    target = float(width) / float(max(1, height))

    def _score(s: tuple[int, int]) -> tuple[float, int]:
        aspect_diff = abs(target - float(s[0]) / float(s[1]))
        # Tie-break on equal aspect ratios by preferring the closest resolution.
        size_diff = abs(s[0] - int(width)) + abs(s[1] - int(height))
        return (aspect_diff, size_diff)

    return min(FIREFLY_VIDEO_SIZES, key=_score)


@dataclass
class _TokenCache:
    access_token: str = ""
    expires_at: float = 0.0

    def valid(self) -> bool:
        return bool(self.access_token) and time.time() < self.expires_at - 60


_token_cache: _TokenCache = _TokenCache()


def _closest_aspect_ratio(width: int, height: int) -> str:
    target = float(width) / float(max(1, height))

    def _score(r: str) -> float:
        w, h = r.split(":")
        return abs(target - float(w) / float(h))

    return min(FIREFLY_ASPECT_RATIOS, key=_score)


def _image_to_jpeg_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=92)
    return buf.getvalue()


class FireflyClient:
    """Adobe Firefly v3 image generation client with custom model support."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str = FIREFLY_API_BASE,
    ) -> None:
        self.client_id = str(client_id or "").strip()
        self.client_secret = str(client_secret or "").strip()
        self.base_url = str(base_url or FIREFLY_API_BASE).rstrip("/")
        if not self.client_id or not self.client_secret:
            raise UserFacingError(
                "Adobe Firefly credentials are not configured.",
                hint=(
                    "Open Settings → Adobe Firefly and save your Adobe Client ID "
                    "and Client Secret, then retry."
                ),
                code="FIREFLY_CREDENTIALS_MISSING",
                status_code=400,
            )

    # ── OAuth token ───────────────────────────────────────────────────────────

    def _access_token(self) -> str:
        global _token_cache
        if _token_cache.valid():
            return _token_cache.access_token

        resp = requests.post(
            ADOBE_IMS_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": FIREFLY_SCOPE,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        if resp.status_code >= 400:
            try:
                err = resp.json().get("error_description") or resp.text[:200]
            except Exception:
                err = resp.text[:200]
            raise UserFacingError(
                f"Adobe IMS token exchange failed: {err}",
                hint=(
                    "Check your Adobe Client ID and Client Secret in Settings → Adobe Firefly. "
                    "Make sure the credentials have the Firefly API scope enabled."
                ),
                code="FIREFLY_TOKEN_FAILED",
                status_code=401,
            )

        data = resp.json()
        token = str(data.get("access_token") or "")
        expires_in = int(data.get("expires_in") or 86400)
        _token_cache = _TokenCache(access_token=token, expires_at=time.time() + expires_in)
        return token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token()}",
            "x-api-key": self.client_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── Image generation ──────────────────────────────────────────────────────

    def generate_image(
        self,
        *,
        prompt: str,
        width: int,
        height: int,
        negative_prompt: str = "",
        seed: int | None = None,
        style: str = "none",
        content_class: str = "photo",
        custom_model_id: str | None = None,
        init_image: Image.Image | None = None,
        strength: float | None = None,
        num_variations: int = 1,
        timeout_s: float = 180.0,
    ) -> FireflyImageResult:
        """Generate an image via Firefly, optionally using a custom fine-tuned model."""

        aspect_ratio = _closest_aspect_ratio(int(width), int(height))
        style_l = str(style or "none").strip().lower()
        if style_l not in FIREFLY_STYLES:
            style_l = "none"
        content_class_l = str(content_class or "photo").strip().lower()
        if content_class_l not in CONTENT_CLASSES:
            content_class_l = "photo"

        body: dict[str, Any] = {
            "numVariations": max(1, min(4, int(num_variations))),
            "prompt": str(prompt or "").strip() or "cinematic still",
            "size": {
                "type": "AspectRatio",
                "aspectRatio": aspect_ratio,
            },
            "photoSettings": {
                "aperture": 1.4,
            },
        }

        if negative_prompt:
            body["negativePrompt"] = str(negative_prompt)[:1000]

        if seed is not None:
            body["seeds"] = [int(seed)]

        if style_l != "none":
            body["styles"] = {"presets": [style_l]}

        if content_class_l != "photo":
            body["contentClass"] = content_class_l

        if custom_model_id:
            body["customModel"] = {"id": str(custom_model_id)}

        # Image-to-image: upload reference image, get upload presigned URL
        if init_image is not None:
            upload_id = self._upload_reference_image(init_image, timeout_s=30.0)
            body["image"] = {
                "id": upload_id,
                "strength": max(0.1, min(1.0, float(strength or 0.6))),
            }
            endpoint = f"{self.base_url}/v3/images/generate-similar"
        else:
            endpoint = f"{self.base_url}/v3/images/generate"

        resp = requests.post(
            endpoint,
            headers=self._headers(),
            json=body,
            timeout=(30, timeout_s),
        )
        if resp.status_code >= 400:
            self._raise_api_error(resp)

        data = resp.json()
        outputs = data.get("outputs") or []
        if not outputs:
            raise UserFacingError(
                "Adobe Firefly returned no output images.",
                hint="Retry the render. If it keeps failing, check your quota in Adobe's portal.",
                code="FIREFLY_NO_OUTPUT",
                status_code=502,
            )

        # Download and decode the first output image
        image_url = (outputs[0].get("image") or {}).get("url") or ""
        generation_id = data.get("jobId") or (outputs[0].get("seed") and None)
        seed_out = outputs[0].get("seed")

        if not image_url:
            raise UserFacingError(
                "Adobe Firefly returned an output without a download URL.",
                hint="Retry the render.",
                code="FIREFLY_NO_IMAGE_URL",
                status_code=502,
            )

        image = self._download_image(image_url, width=int(width), height=int(height))
        return FireflyImageResult(
            image=image,
            model="firefly-image-3",
            custom_model_id=str(custom_model_id) if custom_model_id else None,
            seed=int(seed_out) if seed_out is not None else None,
            generation_id=str(generation_id) if generation_id else None,
        )

    def _upload_reference_image(self, image: Image.Image, *, timeout_s: float) -> str:
        """Upload an init image via the Firefly upload API and return the asset id."""
        upload_url = f"{self.base_url}/v3/storage/image"
        jpg_bytes = _image_to_jpeg_bytes(image)
        resp = requests.post(
            upload_url,
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "x-api-key": self.client_id,
                "Content-Type": "image/jpeg",
                "Accept": "application/json",
            },
            data=jpg_bytes,
            timeout=(30, timeout_s),
        )
        if resp.status_code >= 400:
            self._raise_api_error(resp)
        asset_id = resp.json().get("images", [{}])[0].get("id") or ""
        if not asset_id:
            raise UserFacingError(
                "Adobe Firefly image upload did not return an asset id.",
                hint="Retry the render.",
                code="FIREFLY_UPLOAD_FAILED",
                status_code=502,
            )
        return asset_id

    def _download_image(self, url: str, *, width: int, height: int) -> Image.Image:
        resp = requests.get(url, timeout=(15, 120))
        resp.raise_for_status()
        try:
            img = Image.open(io.BytesIO(resp.content))
            img = ImageOps.exif_transpose(img).convert("RGB")
            if img.size != (width, height):
                img = ImageOps.fit(img, (width, height), method=Image.LANCZOS)
            return img
        except Exception as exc:
            raise UserFacingError(
                "Adobe Firefly returned image data Studio could not decode.",
                hint="Retry the render. If it keeps failing, change output settings.",
                code="FIREFLY_IMAGE_DECODE_FAILED",
                status_code=502,
            ) from exc

    # ── Video generation ──────────────────────────────────────────────────────

    def generate_video(
        self,
        *,
        prompt: str,
        width: int,
        height: int,
        duration_s: float = 5.0,
        negative_prompt: str = "",
        seed: int | None = None,
        custom_model_id: str | None = None,
        init_image: Image.Image | None = None,
        timeout_s: float = 600.0,
        poll_interval_s: float = 5.0,
    ) -> FireflyVideoResult:
        """Generate a video clip via the async Firefly Video API.

        Submits a generation job, polls its status until it succeeds, then
        downloads the resulting MP4. Works for text-to-video and, when
        ``init_image`` is given, image-to-video.
        """

        size_w, size_h = _closest_video_size(int(width), int(height))
        clip_seconds = max(
            FIREFLY_VIDEO_MIN_SECONDS,
            min(FIREFLY_VIDEO_MAX_SECONDS, int(round(float(duration_s) or 5.0))),
        )

        body: dict[str, Any] = {
            "prompt": str(prompt or "").strip() or "cinematic music video clip",
            "sizes": [{"width": int(size_w), "height": int(size_h)}],
            "videoSettings": {"durationInSeconds": clip_seconds},
        }
        if negative_prompt:
            body["negativePrompt"] = str(negative_prompt)[:1000]
        if seed is not None:
            body["seeds"] = [int(seed)]
        if custom_model_id:
            body["customModel"] = {"id": str(custom_model_id)}
        if init_image is not None:
            upload_id = self._upload_reference_image(init_image, timeout_s=30.0)
            body["image"] = {"id": upload_id}

        resp = requests.post(
            f"{self.base_url}/v3/videos/generate",
            headers=self._headers(),
            json=body,
            timeout=(30, 120),
        )
        if resp.status_code >= 400:
            self._raise_api_error(resp)

        submit = resp.json() if resp.content else {}
        status_url = self._job_status_url(submit)
        job_id = str(submit.get("jobId") or submit.get("id") or "") or None

        outputs, result_seed = self._poll_video_job(
            status_url, timeout_s=timeout_s, poll_interval_s=poll_interval_s
        )
        video_url = self._extract_video_url(outputs)
        if not video_url:
            raise UserFacingError(
                "Adobe Firefly returned no downloadable video.",
                hint="Retry the render. If it keeps failing, check your Firefly video quota.",
                code="FIREFLY_VIDEO_NO_OUTPUT",
                status_code=502,
            )

        video_bytes, content_type = self._download_bytes(video_url)
        return FireflyVideoResult(
            video_bytes=video_bytes,
            content_type=content_type or "video/mp4",
            model="firefly-video",
            seed=int(result_seed) if result_seed is not None else seed,
            generation_id=job_id,
            duration_s=float(clip_seconds),
        )

    def _job_status_url(self, submit: dict[str, Any]) -> str:
        links = submit.get("links") if isinstance(submit.get("links"), dict) else {}
        status_url = (
            submit.get("statusUrl")
            or submit.get("status_url")
            or (links.get("status") if isinstance(links, dict) else None)
            or ""
        )
        if status_url:
            return str(status_url)
        job_id = str(submit.get("jobId") or submit.get("id") or "").strip()
        if job_id:
            return f"{self.base_url}/v3/status/{job_id}"
        raise UserFacingError(
            "Adobe Firefly did not return a video job handle.",
            hint="Retry the render.",
            code="FIREFLY_VIDEO_NO_JOB",
            status_code=502,
        )

    def _poll_video_job(
        self, status_url: str, *, timeout_s: float, poll_interval_s: float
    ) -> tuple[list[dict[str, Any]], int | None]:
        deadline = time.time() + max(30.0, float(timeout_s))
        delay = max(1.0, float(poll_interval_s))
        while True:
            resp = requests.get(status_url, headers=self._headers(), timeout=(15, 60))
            if resp.status_code >= 400:
                self._raise_api_error(resp)
            data = resp.json() if resp.content else {}
            status = str(data.get("status") or "").strip().lower()
            if status in ("succeeded", "complete", "completed", "done"):
                result = data.get("result") if isinstance(data.get("result"), dict) else data
                outputs = result.get("outputs") or data.get("outputs") or []
                seed = None
                if outputs and isinstance(outputs[0], dict):
                    seed = outputs[0].get("seed")
                return list(outputs), (int(seed) if seed is not None else None)
            if status in ("failed", "error", "cancelled", "canceled"):
                raise UserFacingError(
                    f"Adobe Firefly video job {status or 'failed'}.",
                    hint="Retry the render. If it keeps failing, check your Firefly quota and prompt.",
                    code="FIREFLY_VIDEO_JOB_FAILED",
                    status_code=502,
                )
            if time.time() >= deadline:
                raise UserFacingError(
                    "Adobe Firefly video job timed out.",
                    hint="The clip took too long to render. Try a shorter duration or smaller size.",
                    code="FIREFLY_VIDEO_TIMEOUT",
                    status_code=504,
                )
            time.sleep(delay)

    @staticmethod
    def _extract_video_url(outputs: list[dict[str, Any]]) -> str:
        for out in outputs or []:
            if not isinstance(out, dict):
                continue
            video = out.get("video") if isinstance(out.get("video"), dict) else {}
            url = (
                video.get("url")
                or (out.get("destination") or {}).get("url")
                if isinstance(out.get("destination"), dict)
                else video.get("url")
            )
            url = url or video.get("url") or out.get("url") or ""
            if url:
                return str(url)
        return ""

    def _download_bytes(self, url: str) -> tuple[bytes, str]:
        resp = requests.get(url, timeout=(15, 300))
        resp.raise_for_status()
        return resp.content, str(resp.headers.get("Content-Type") or "")

    def _raise_api_error(self, response: requests.Response) -> None:
        message = f"Adobe Firefly request failed with status {response.status_code}."
        hint = "Check your Adobe credentials and Firefly API settings, then retry."
        try:
            payload = response.json()
            msg = (
                payload.get("message")
                or payload.get("error_description")
                or (payload.get("errors") or [""])[0]
                or ""
            )
            if msg:
                message = f"Adobe Firefly error: {msg}"
            if response.status_code in (401, 403):
                hint = (
                    "Open Settings → Adobe Firefly, verify your Client ID and Client Secret, "
                    "and make sure the credentials have the Firefly API scope enabled."
                )
            elif response.status_code == 429:
                hint = "Adobe Firefly rate limit hit. Wait a moment, then retry."
            elif response.status_code == 402:
                hint = "Adobe Firefly quota exceeded. Check your plan in Adobe's developer portal."
        except Exception:
            pass
        raise UserFacingError(
            message,
            hint=hint,
            code="FIREFLY_API_ERROR",
            status_code=502 if response.status_code < 500 else response.status_code,
        )
