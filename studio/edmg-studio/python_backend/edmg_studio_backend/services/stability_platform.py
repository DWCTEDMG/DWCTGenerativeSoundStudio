from __future__ import annotations

import base64
import io
import time
from dataclasses import dataclass
from typing import Any

import requests
from PIL import Image, ImageOps

from ..errors import UserFacingError


ALLOWED_ASPECT_RATIOS = ("21:9", "16:9", "3:2", "5:4", "1:1", "4:5", "2:3", "9:16", "9:21")
STYLE_PRESETS = (
    "none",
    "enhance",
    "anime",
    "photographic",
    "digital-art",
    "comic-book",
    "fantasy-art",
    "line-art",
    "analog-film",
    "neon-punk",
    "isometric",
    "low-poly",
    "origami",
    "modeling-compound",
    "cinematic",
    "3d-model",
    "pixel-art",
    "tile-texture",
)
SD3_MODELS = ("sd3.5-large", "sd3.5-large-turbo", "sd3.5-medium")


@dataclass(frozen=True)
class StabilityImageResult:
    image: Image.Image
    service: str
    model: str | None
    seed: int | None = None
    finish_reason: str | None = None
    generation_id: str | None = None


def _closest_aspect_ratio(width: int, height: int) -> str:
    target = float(width) / float(max(1, height))

    def _score(ratio: str) -> float:
        left, right = ratio.split(":")
        return abs(target - (float(left) / float(right)))

    return min(ALLOWED_ASPECT_RATIOS, key=_score)


def _image_to_png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _decode_image_response(response: requests.Response) -> tuple[bytes, dict[str, Any]]:
    content_type = str(response.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("image"):
            raise UserFacingError(
                "Stability Platform returned an unexpected JSON response.",
                hint="Check the render log for the raw provider response, then retry.",
                code="STABILITY_BAD_RESPONSE",
                status_code=502,
            )
        raw = base64.b64decode(str(payload["image"]))
        return raw, payload
    return response.content, {}


class StabilityPlatformClient:
    def __init__(self, api_key: str, base_url: str = "https://api.stability.ai"):
        self.api_key = str(api_key or "").strip()
        self.base_url = str(base_url or "https://api.stability.ai").rstrip("/")
        if not self.api_key:
            raise UserFacingError(
                "Stability API key is not configured.",
                hint="Open Settings and save a Stability API key, then retry.",
                code="STABILITY_API_KEY_MISSING",
                status_code=400,
            )

    def generate_image(
        self,
        *,
        prompt: str,
        width: int,
        height: int,
        service: str = "sd3",
        model: str = "sd3.5-large-turbo",
        style_preset: str = "none",
        negative_prompt: str = "",
        seed: int | None = None,
        init_image: Image.Image | None = None,
        strength: float | None = None,
        cfg_scale: float | None = None,
        output_format: str = "png",
        timeout_s: float = 180.0,
    ) -> StabilityImageResult:
        service_l = str(service or "sd3").strip().lower()
        if service_l not in {"core", "ultra", "sd3"}:
            raise UserFacingError(
                f"Unsupported Stability service: {service}",
                hint="Choose one of: core, ultra, or sd3.",
                code="STABILITY_UNSUPPORTED_SERVICE",
                status_code=400,
            )
        model_l = str(model or "sd3.5-large-turbo").strip().lower()
        if service_l == "sd3" and model_l not in SD3_MODELS:
            model_l = "sd3.5-large-turbo"
        style_l = str(style_preset or "none").strip().lower()
        if style_l not in STYLE_PRESETS:
            style_l = "none"
        output_format_l = str(output_format or "png").strip().lower()
        if output_format_l not in {"png", "jpeg", "webp"}:
            output_format_l = "png"

        aspect_ratio = _closest_aspect_ratio(int(width), int(height))
        path = {
            "core": "/v2beta/stable-image/generate/core",
            "ultra": "/v2beta/stable-image/generate/ultra",
            "sd3": "/v2beta/stable-image/generate/sd3",
        }[service_l]
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "stability-client-id": "EDMG Studio",
            "stability-client-version": "1.1.0",
        }
        files: list[tuple[str, tuple[Any, ...]]] = [
            ("prompt", (None, str(prompt or "").strip() or "cinematic")),
            ("aspect_ratio", (None, aspect_ratio)),
            ("output_format", (None, output_format_l)),
        ]
        if negative_prompt:
            files.append(("negative_prompt", (None, str(negative_prompt))))
        if style_l != "none":
            files.append(("style_preset", (None, style_l)))
        if seed is not None:
            files.append(("seed", (None, str(int(seed)))))

        if service_l == "sd3":
            files.append(("model", (None, model_l)))
            if init_image is not None:
                files.append(("mode", (None, "image-to-image")))
                files.append(
                    ("image", ("init.png", _image_to_png_bytes(init_image.convert("RGB")), "image/png"))
                )
                files.append(("strength", (None, str(max(0.1, min(1.0, float(strength or 0.55)))))))
            else:
                files.append(("mode", (None, "text-to-image")))
            if cfg_scale is not None:
                files.append(("cfg_scale", (None, str(max(1.0, min(10.0, float(cfg_scale)))))))
        elif service_l == "ultra" and init_image is not None:
            files.append(("image", ("init.png", _image_to_png_bytes(init_image.convert("RGB")), "image/png")))
            files.append(("strength", (None, str(max(0.1, min(1.0, float(strength or 0.55)))))))

        response = requests.post(
            f"{self.base_url}{path}",
            files=files,
            headers=headers,
            timeout=(30, timeout_s),
        )
        if response.status_code == 202:
            response = self._poll_result(str(response.json().get("id") or ""), timeout_s=timeout_s)
        if response.status_code >= 400:
            self._raise_api_error(response)

        raw_bytes, payload = _decode_image_response(response)
        try:
            image = Image.open(io.BytesIO(raw_bytes))
            image = ImageOps.exif_transpose(image).convert("RGB")
            if image.size != (int(width), int(height)):
                image = ImageOps.fit(image, (int(width), int(height)), method=Image.LANCZOS)
        except Exception as exc:
            raise UserFacingError(
                "Stability Platform returned image data Studio could not decode.",
                hint="Retry the render. If it keeps failing, switch the hosted model or output format in Settings.",
                code="STABILITY_IMAGE_DECODE_FAILED",
                status_code=502,
            ) from exc
        return StabilityImageResult(
            image=image,
            service=service_l,
            model=(model_l if service_l == "sd3" else None),
            seed=payload.get("seed") if isinstance(payload, dict) else None,
            finish_reason=payload.get("finish_reason") if isinstance(payload, dict) else None,
            generation_id=payload.get("id") if isinstance(payload, dict) else None,
        )

    def _poll_result(self, generation_id: str, *, timeout_s: float) -> requests.Response:
        if not generation_id:
            raise UserFacingError(
                "Stability Platform returned an async generation without an id.",
                hint="Retry the render. If the issue persists, check the provider status in Settings.",
                code="STABILITY_ASYNC_ID_MISSING",
                status_code=502,
            )
        deadline = time.time() + max(10.0, float(timeout_s))
        last_response: requests.Response | None = None
        while time.time() < deadline:
            response = requests.get(
                f"{self.base_url}/v2beta/results/{generation_id}",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Accept": "application/json",
                },
                timeout=(15, 60),
            )
            last_response = response
            if response.status_code != 202:
                return response
            time.sleep(2.0)
        if last_response is not None:
            return last_response
        raise UserFacingError(
            "Stability Platform timed out while waiting for a hosted image.",
            hint="Retry the render or pick a faster hosted model in Settings.",
            code="STABILITY_TIMEOUT",
            status_code=504,
        )

    def _raise_api_error(self, response: requests.Response) -> None:
        message = f"Stability Platform request failed with status {response.status_code}."
        hint = "Check the Stability API key and hosted render settings, then retry."
        try:
            payload = response.json()
            errors = payload.get("errors") if isinstance(payload, dict) else None
            name = payload.get("name") if isinstance(payload, dict) else None
            if isinstance(errors, list) and errors:
                message = "; ".join(str(x) for x in errors[:3])
            elif isinstance(name, str) and name:
                message = f"Stability Platform error: {name}"
            if response.status_code in (401, 403):
                hint = "Open Settings, save a valid Stability API key, and retry the hosted render."
            elif response.status_code == 429:
                hint = "The Stability API rate limit was hit. Wait a moment, then retry."
        except Exception:
            pass
        raise UserFacingError(
            message,
            hint=hint,
            code="STABILITY_API_ERROR",
            status_code=502 if response.status_code < 500 else response.status_code,
        )
