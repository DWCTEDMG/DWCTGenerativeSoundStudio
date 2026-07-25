"""NVIDIA Cosmos video generation client for DWCT Generative Sound Studio.

Cosmos World Foundation Models are shipped as **self-hosted NIM containers**, not as a
hosted REST route on the NVIDIA API Catalog. There is no public
``https://ai.api.nvidia.com/v1/cosmos/...`` text→video endpoint — the catalog only exposes
the Cosmos *reasoning* VLM, not the Predict / Cosmos3 video generators. So this client talks
to a NIM you run yourself.

Supported NIMs (all served at ``POST {base_url}/v1/infer``):
  - Cosmos-Predict1-7B-Text2World   : text → video      (``text2world``)
  - Cosmos-Predict1-7B-Video2World  : image → video      (``video2world``)
  - Cosmos3-Generator               : text/image → video (``cosmos3``)

Request shapes differ by family:
  - Predict1 uses ``video_params`` (height/width/frames_count/frames_per_sec) plus
    ``prompt_upsampling``; guidance_scale is clamped to [1, 10] and steps to [1, 50].
  - Cosmos3 uses a string ``resolution`` key (e.g. ``"720_16_9"``) plus ``num_output_frames``
    (4k+1 cadence) and ``fps``; guidance_scale is clamped to [1, 7] and steps to [1, 100].
    Cosmos3 rejects unknown fields with HTTP 422, so Predict1-only fields are never sent.

Config:
  Set the NIM URL via render settings ``cosmos.base_url`` (Settings → GPU / Render Runtime →
  Cosmos). The client appends ``/v1/infer``. A NIM container typically needs no API key; if
  one is provided it is sent as a Bearer token.

Response:
  The NIM returns ``{"b64_video": "<base64-mp4>", "seed": ...}``. The client decodes and saves
  it to disk, returning the path.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from PIL import Image

from ..errors import UserFacingError


COSMOS_MODELS: dict[str, str] = {
    "text2world":  "cosmos-predict1-7b-text2world",
    "video2world": "cosmos-predict1-7b-video2world",
    "cosmos3":     "cosmos3-generator",
}

_COSMOS3_SLUG = COSMOS_MODELS["cosmos3"]

# ── Cosmos-Predict1 supported output resolutions (width x height) ─────────────
# Per NVIDIA NIM docs: 1:1 960x960, 4:3 960x704, 3:4 704x960, 16:9 1280x704, 9:16 704x1280.
COSMOS_RESOLUTIONS = (
    (1280, 704),   # 16:9
    (704, 1280),   # 9:16
    (960, 960),    # 1:1
    (960, 704),    # 4:3
    (704, 960),    # 3:4
)

# ── Cosmos3-Generator resolution keys → output pixel shape (width, height) ────
# From the "Output resolution shapes for Cosmos3-Generator" table in the NIM docs.
_COSMOS3_SHAPES: dict[str, tuple[int, int]] = {
    "256_16_9": (320, 192),  "480_16_9": (832, 480),  "720_16_9": (1280, 720),
    "256_1_1":  (256, 256),  "480_1_1":  (640, 640),  "720_1_1":  (960, 960),
    "256_9_16": (192, 320),  "480_9_16": (480, 832),  "720_9_16": (720, 1280),
    "256_4_3":  (320, 256),  "480_4_3":  (736, 544),  "720_4_3":  (1104, 832),
    "256_3_4":  (256, 320),  "480_3_4":  (544, 736),  "720_3_4":  (832, 1104),
}
_COSMOS3_TIERS = (256, 480, 720)
# Aspect suffix → target width/height ratio.
_COSMOS3_ASPECTS: tuple[tuple[str, float], ...] = (
    ("_16_9", 16 / 9),
    ("_1_1",  1.0),
    ("_9_16", 9 / 16),
    ("_4_3",  4 / 3),
    ("_3_4",  3 / 4),
)
# Per-tier maximum num_output_frames (4k+1 cadence).
_COSMOS3_FRAME_CAP: dict[int, int] = {256: 397, 480: 297, 720: 197}
_COSMOS3_FRAME_MIN = 25


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
    """Nearest Cosmos-Predict1 (width, height) by aspect ratio."""
    target_ratio = width / max(1, height)
    return min(
        COSMOS_RESOLUTIONS,
        key=lambda wh: abs((wh[0] / wh[1]) - target_ratio),
    )


def _cosmos3_tier(width: int, height: int) -> int:
    """Pick the Cosmos3 resolution tier from the requested short side."""
    short_side = min(int(width), int(height))
    return min(_COSMOS3_TIERS, key=lambda t: abs(t - short_side))


def _cosmos3_resolution_key(width: int, height: int) -> str:
    """Map a requested width/height to a Cosmos3 ``"<tier>_<aspect>"`` key."""
    tier = _cosmos3_tier(width, height)
    target_ratio = int(width) / max(1, int(height))
    suffix = min(_COSMOS3_ASPECTS, key=lambda a: abs(a[1] - target_ratio))[0]
    return f"{tier}{suffix}"


def _cosmos3_frames(num_frames: int, tier: int) -> int:
    """Snap frame count to the 4k+1 cadence within [25, per-tier cap]."""
    cap = _COSMOS3_FRAME_CAP.get(tier, 197)
    n = max(_COSMOS3_FRAME_MIN, min(int(num_frames), cap))
    # 4k+1 cadence: 25, 29, 33, ... → round to nearest valid value.
    k = round((n - 1) / 4)
    snapped = 4 * k + 1
    if snapped < _COSMOS3_FRAME_MIN:
        snapped = _COSMOS3_FRAME_MIN
    if snapped > cap:
        snapped = 4 * ((cap - 1) // 4) + 1
    return snapped


def _image_to_b64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=92)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class CosmosClient:
    """NVIDIA Cosmos video generation client (self-hosted NIM).

    Point ``base_url`` at a running Cosmos NIM container; the client appends ``/v1/infer``.
    An API key is optional for NIM auth and only sent when provided.
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        timeout_s: float = 600.0,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.timeout_s = float(timeout_s)

    def _endpoint(self) -> str:
        if not self.base_url:
            raise UserFacingError(
                "Cosmos NIM URL is not configured.",
                hint=(
                    "Cosmos video generation runs on a self-hosted NVIDIA NIM container — there is "
                    "no hosted Cosmos video endpoint on the NVIDIA API Catalog. Start a Cosmos NIM "
                    "(e.g. cosmos3-generator) on a CUDA GPU, then set its URL in "
                    "Settings → GPU / Render Runtime → Cosmos (Base URL), for example "
                    "http://127.0.0.1:8000. The Studio appends /v1/infer automatically."
                ),
                code="COSMOS_NIM_NOT_CONFIGURED",
                status_code=400,
            )
        return f"{self.base_url}/v1/infer"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

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
        model: str = "cosmos3",
    ) -> CosmosVideoResult:
        """Generate a video clip from a text prompt using a Cosmos NIM."""
        slug = COSMOS_MODELS.get(model, _COSMOS3_SLUG)
        clean_prompt = str(prompt or "cinematic music video").strip()

        if slug == _COSMOS3_SLUG:
            body, out_w, out_h, out_frames = self._cosmos3_body(
                prompt=clean_prompt,
                negative_prompt=negative_prompt,
                width=width, height=height, fps=fps, num_frames=num_frames,
                steps=steps, guidance_scale=guidance_scale, seed=seed,
            )
            return self._call_and_save(body, out_path, model=slug, fps=fps,
                                       width=out_w, height=out_h, frames=out_frames)

        body, res_w, res_h = self._predict1_body(
            negative_prompt=negative_prompt, width=width, height=height, fps=fps,
            num_frames=num_frames, steps=steps, guidance_scale=guidance_scale, seed=seed,
        )
        body["prompt"] = clean_prompt
        body["prompt_upsampling"] = bool(prompt_upsampling)
        return self._call_and_save(body, out_path, model=slug, fps=fps,
                                   width=res_w, height=res_h,
                                   frames=int(body["video_params"]["frames_count"]))

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
        """Generate a video continuation from a still image using a Cosmos NIM."""
        slug = COSMOS_MODELS.get(model, COSMOS_MODELS["video2world"])
        img_b64 = _image_to_b64(image)
        image_field = f"data:image/jpeg;base64,{img_b64}"

        if slug == _COSMOS3_SLUG:
            body, out_w, out_h, out_frames = self._cosmos3_body(
                prompt=str(prompt or "").strip(),
                negative_prompt=negative_prompt,
                width=width, height=height, fps=fps, num_frames=num_frames,
                steps=steps, guidance_scale=guidance_scale, seed=seed,
            )
            body["image"] = image_field
            return self._call_and_save(body, out_path, model=slug, fps=fps,
                                       width=out_w, height=out_h, frames=out_frames)

        body, res_w, res_h = self._predict1_body(
            negative_prompt=negative_prompt, width=width, height=height, fps=fps,
            num_frames=num_frames, steps=steps, guidance_scale=guidance_scale, seed=seed,
        )
        body["image"] = image_field
        if prompt:
            body["prompt"] = str(prompt).strip()
        return self._call_and_save(body, out_path, model=slug, fps=fps,
                                   width=res_w, height=res_h,
                                   frames=int(body["video_params"]["frames_count"]))

    # ── Request builders ────────────────────────────────────────────────────────

    def _predict1_body(
        self,
        *,
        negative_prompt: str,
        width: int,
        height: int,
        fps: float,
        num_frames: int,
        steps: int,
        guidance_scale: float,
        seed: int | None,
    ) -> tuple[dict[str, Any], int, int]:
        res_w, res_h = _closest_resolution(width, height)
        body: dict[str, Any] = {
            "negative_prompt": str(negative_prompt or "").strip(),
            "guidance_scale": max(1.0, min(10.0, float(guidance_scale))),
            "steps": max(1, min(50, int(steps))),
            "video_params": {
                "height": res_h,
                "width": res_w,
                "frames_count": max(25, int(num_frames)),
                "frames_per_sec": max(12.0, min(40.0, float(fps))),
            },
        }
        if seed is not None:
            body["seed"] = int(seed)
        return body, res_w, res_h

    def _cosmos3_body(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        fps: float,
        num_frames: int,
        steps: int,
        guidance_scale: float,
        seed: int | None,
    ) -> tuple[dict[str, Any], int, int, int]:
        resolution = _cosmos3_resolution_key(width, height)
        tier = int(resolution.split("_", 1)[0])
        frames = _cosmos3_frames(num_frames, tier)
        out_w, out_h = _COSMOS3_SHAPES.get(resolution, (width, height))
        body: dict[str, Any] = {
            "guidance_scale": max(1.0, min(7.0, float(guidance_scale))),
            "steps": max(1, min(100, int(steps))),
            "resolution": resolution,
            "num_output_frames": frames,
            "fps": max(1.0, min(60.0, float(fps))),
        }
        if prompt:
            body["prompt"] = prompt
        # Cosmos3 fills an upstream default when negative_prompt is omitted; only send a
        # non-empty override (an explicit "" would disable CFG conditioning).
        neg = str(negative_prompt or "").strip()
        if neg:
            body["negative_prompt"] = neg
        if seed is not None:
            body["seed"] = max(0, int(seed))
        return body, out_w, out_h, frames

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _call_and_save(
        self,
        body: dict[str, Any],
        out_path: Path,
        *,
        model: str,
        fps: float,
        width: int,
        height: int,
        frames: int,
    ) -> CosmosVideoResult:
        endpoint = self._endpoint()
        try:
            resp = requests.post(
                endpoint,
                headers=self._headers(),
                json=body,
                timeout=(30, self.timeout_s),
            )
        except requests.exceptions.ConnectionError as exc:
            raise UserFacingError(
                "Could not reach the Cosmos NIM.",
                hint=(
                    f"No NIM responded at {endpoint}. Confirm the Cosmos NIM container is running "
                    "and the Base URL in Settings → GPU / Render Runtime → Cosmos is correct "
                    "(check GET {base}/v1/health/ready)."
                ),
                code="COSMOS_NIM_UNREACHABLE",
                status_code=502,
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise UserFacingError(
                "Cosmos video generation timed out.",
                hint=(
                    "Cosmos generation can take several minutes for a single clip. "
                    "Increase the timeout in Settings → GPU / Render Runtime → Cosmos, or reduce steps/frames."
                ),
                code="COSMOS_TIMEOUT",
                status_code=504,
            ) from exc

        if resp.status_code >= 400:
            self._raise_api_error(resp)

        data = resp.json()
        b64_video = str(data.get("b64_video") or data.get("video") or "")
        if not b64_video:
            raise UserFacingError(
                "Cosmos returned a response with no video data.",
                hint="Retry the render. If it keeps failing, check the NIM container logs.",
                code="COSMOS_NO_VIDEO",
                status_code=502,
            )

        video_bytes = base64.b64decode(b64_video)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(video_bytes)

        duration_s = frames / max(1.0, fps)
        seed_out = data.get("seed") if data.get("seed") is not None else body.get("seed")

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
        hint = "Check the Cosmos NIM container logs, then retry."
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
            if response.status_code == 404:
                hint = (
                    "The NIM did not recognize /v1/infer at this Base URL. Verify the Base URL points "
                    "at a Cosmos WFM NIM (not the NVIDIA API Catalog) — only a self-hosted NIM serves "
                    "Cosmos video generation."
                )
            elif response.status_code in (401, 403):
                hint = (
                    "The Cosmos NIM rejected the request. If your NIM requires an API key, set the "
                    "NVIDIA API key in Settings → AI Provider; most local NIMs need no key."
                )
            elif response.status_code == 422:
                hint = (
                    "The NIM rejected the request body (invalid parameters). Try a supported resolution "
                    "and frame count, or reduce steps/guidance."
                )
            elif response.status_code == 429:
                hint = "Cosmos NIM is busy / rate limited. Wait a moment, then retry."
        except Exception:
            pass
        raise UserFacingError(
            message,
            hint=hint,
            code="COSMOS_API_ERROR",
            status_code=502 if response.status_code < 500 else response.status_code,
        )
