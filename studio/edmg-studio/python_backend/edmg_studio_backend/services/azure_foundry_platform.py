"""Azure AI Foundry managed-compute video generation client (NVIDIA Cosmos3-Super).

Unlike the self-hosted Cosmos NIM in :mod:`cosmos_platform` (a container you run yourself on a
CUDA GPU), this client talks to a **hosted** Azure AI Foundry ``GlobalManagedCompute`` deployment
of Cosmos3-Super. Foundry managed-compute deployments of "bespoke" NIM containers (as opposed to
OpenAI-compatible chat models) are reverse-proxied at::

    POST {endpoint_url}/managed-deployments/{deployment_name}/v1/messages

which forwards the request body to the underlying Cosmos3-Generator NIM largely unchanged, so this
client reuses the exact same Cosmos3 request-body shape as the self-hosted client (resolution key,
``num_output_frames`` 4k+1 cadence, ``guidance_scale``/``steps`` clamps) — see ``cosmos_platform``
for the authoritative parameter semantics.

Auth: Azure AI Foundry managed-compute deployments use key-based auth, sent as a standard bearer
token: ``Authorization: Bearer <api_key>`` (the same default the Azure OpenAI/Foundry SDKs use for
key auth). Get the key + endpoint from the deployment's "Endpoint" tab in the Foundry portal.

Response parsing is intentionally permissive because the exact ``v1/messages`` response envelope
for this deployment has not been confirmed against a live swagger document: this client accepts a
plain ``{"b64_video": ...}``/``{"video": ...}`` body (identical to the self-hosted NIM), a
chat-style ``choices[0].message.content`` block list containing a video part, a ``data[0]``
container, or a ``video_url`` to download. If none of those shapes match, a clear error is raised
naming the unrecognized response so the mapping can be extended once confirmed.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from PIL import Image

from ..errors import UserFacingError
from .cosmos_platform import (
    _COSMOS3_SHAPES,
    _cosmos3_frames,
    _cosmos3_resolution_key,
    _image_to_b64,
)


@dataclass
class AzureFoundryVideoResult:
    video_path: Path
    model: str
    duration_s: float
    frames: int
    fps: float
    width: int
    height: int
    seed: int | None = None


class AzureFoundryClient:
    """NVIDIA Cosmos3-Super client via an Azure AI Foundry managed-compute deployment."""

    def __init__(
        self,
        api_key: str = "",
        endpoint_url: str = "",
        deployment_name: str = "",
        timeout_s: float = 600.0,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.endpoint_url = str(endpoint_url or "").strip().rstrip("/")
        self.deployment_name = str(deployment_name or "").strip().strip("/")
        self.timeout_s = float(timeout_s)

    def _endpoint(self) -> str:
        if not self.endpoint_url or not self.deployment_name:
            raise UserFacingError(
                "Azure Foundry Cosmos3 is not configured.",
                hint=(
                    "Set the Foundry project/deployment Endpoint URL and Deployment name in "
                    "Settings → GPU / Render Runtime → Azure Foundry Cosmos3, and set the API key "
                    "in the Secrets section. Both come from the deployment's Endpoint tab in the "
                    "Azure AI Foundry portal."
                ),
                code="AZURE_FOUNDRY_NOT_CONFIGURED",
                status_code=400,
            )
        return f"{self.endpoint_url}/managed-deployments/{self.deployment_name}/v1/messages"

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise UserFacingError(
                "Azure Foundry API key is not set.",
                hint="Set the Azure Foundry API key in Settings → Secrets, then retry.",
                code="AZURE_FOUNDRY_NO_API_KEY",
                status_code=400,
            )
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    # ── Text-to-video ─────────────────────────────────────────────────────────

    def text_to_video(
        self,
        *,
        prompt: str,
        out_path: Path,
        negative_prompt: str = "blurry, low quality, text, watermark, logo",
        width: int = 1280,
        height: int = 720,
        fps: float = 24.0,
        num_frames: int = 121,
        steps: int = 50,
        guidance_scale: float = 7.0,
        seed: int | None = None,
    ) -> AzureFoundryVideoResult:
        """Generate a video clip from a text prompt via the Foundry Cosmos3-Super deployment."""
        body, out_w, out_h, out_frames = self._cosmos3_body(
            prompt=str(prompt or "cinematic music video").strip(),
            negative_prompt=negative_prompt,
            width=width, height=height, fps=fps, num_frames=num_frames,
            steps=steps, guidance_scale=guidance_scale, seed=seed,
        )
        return self._call_and_save(body, out_path, fps=fps, width=out_w, height=out_h, frames=out_frames)

    # ── Image-to-video ────────────────────────────────────────────────────────

    def image_to_video(
        self,
        *,
        image: Image.Image,
        out_path: Path,
        prompt: str = "",
        negative_prompt: str = "blurry, low quality, text, watermark, logo",
        width: int = 1280,
        height: int = 720,
        fps: float = 24.0,
        num_frames: int = 121,
        steps: int = 50,
        guidance_scale: float = 7.0,
        seed: int | None = None,
    ) -> AzureFoundryVideoResult:
        """Generate a video continuation from a still image via the Foundry deployment."""
        body, out_w, out_h, out_frames = self._cosmos3_body(
            prompt=str(prompt or "").strip(),
            negative_prompt=negative_prompt,
            width=width, height=height, fps=fps, num_frames=num_frames,
            steps=steps, guidance_scale=guidance_scale, seed=seed,
        )
        body["image"] = f"data:image/jpeg;base64,{_image_to_b64(image)}"
        return self._call_and_save(body, out_path, fps=fps, width=out_w, height=out_h, frames=out_frames)

    # ── Request builder ──────────────────────────────────────────────────────

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
        fps: float,
        width: int,
        height: int,
        frames: int,
    ) -> AzureFoundryVideoResult:
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
                "Could not reach the Azure Foundry deployment.",
                hint=(
                    f"No response from {endpoint}. Confirm the Endpoint URL and Deployment name in "
                    "Settings → GPU / Render Runtime → Azure Foundry Cosmos3 are correct and the "
                    "deployment is running."
                ),
                code="AZURE_FOUNDRY_UNREACHABLE",
                status_code=502,
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise UserFacingError(
                "Azure Foundry Cosmos3 video generation timed out.",
                hint=(
                    "Generation can take several minutes for a single clip. Increase the timeout in "
                    "Settings → GPU / Render Runtime → Azure Foundry Cosmos3, or reduce steps/frames."
                ),
                code="AZURE_FOUNDRY_TIMEOUT",
                status_code=504,
            ) from exc

        if resp.status_code >= 400:
            self._raise_api_error(resp)

        data = resp.json()
        b64_video, seed_out = self._extract_video(data)
        if not b64_video:
            raise UserFacingError(
                "Azure Foundry returned a response with no recognizable video data.",
                hint=(
                    "The deployment responded successfully, but the response shape did not match "
                    "any known Cosmos3/Foundry envelope. Retry the render; if it keeps failing, "
                    "capture the raw response body so the parsing can be extended."
                ),
                code="AZURE_FOUNDRY_NO_VIDEO",
                status_code=502,
            )

        video_bytes = base64.b64decode(b64_video)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(video_bytes)

        duration_s = frames / max(1.0, fps)
        seed_final = seed_out if seed_out is not None else body.get("seed")

        return AzureFoundryVideoResult(
            video_path=out_path,
            model="cosmos3-super",
            duration_s=duration_s,
            frames=frames,
            fps=fps,
            width=width,
            height=height,
            seed=int(seed_final) if seed_final is not None else None,
        )

    @staticmethod
    def _extract_video(data: Any) -> tuple[str, int | None]:
        """Best-effort extraction of a base64 video + seed from several plausible envelopes."""
        if not isinstance(data, dict):
            return "", None

        seed = data.get("seed")

        # 1) Same flat shape as the self-hosted Cosmos NIM.
        flat = data.get("b64_video") or data.get("video")
        if isinstance(flat, str) and flat:
            return flat, seed

        # 2) Chat-style envelope: choices[0].message.content = [...] with a video part.
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = (choices[0] or {}).get("message") if isinstance(choices[0], dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str) and content:
                return content, seed
            if isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    for key in ("video_base64", "b64_video", "video"):
                        val = part.get(key)
                        if isinstance(val, str) and val:
                            return val, seed
                    url = part.get("video_url") or part.get("url")
                    if isinstance(url, str) and url:
                        downloaded = AzureFoundryClient._download_b64(url)
                        if downloaded:
                            return downloaded, seed

        # 3) OpenAI-style data[] container.
        items = data.get("data")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            first = items[0]
            for key in ("b64_video", "b64_json", "video"):
                val = first.get(key)
                if isinstance(val, str) and val:
                    return val, seed
            url = first.get("video_url") or first.get("url")
            if isinstance(url, str) and url:
                downloaded = AzureFoundryClient._download_b64(url)
                if downloaded:
                    return downloaded, seed

        # 4) A top-level download URL.
        url = data.get("video_url")
        if isinstance(url, str) and url:
            downloaded = AzureFoundryClient._download_b64(url)
            if downloaded:
                return downloaded, seed

        return "", seed

    @staticmethod
    def _download_b64(url: str) -> str:
        try:
            resp = requests.get(url, timeout=(15, 120))
            resp.raise_for_status()
            return base64.b64encode(resp.content).decode("ascii")
        except Exception:
            return ""

    def _raise_api_error(self, response: requests.Response) -> None:
        message = f"Azure Foundry request failed ({response.status_code})."
        hint = "Check the deployment status in the Azure AI Foundry portal, then retry."
        try:
            payload = response.json()
            detail = (
                payload.get("error", {}).get("message")
                if isinstance(payload.get("error"), dict)
                else None
            ) or payload.get("detail") or payload.get("message") or ""
            if detail:
                message = f"Azure Foundry error: {detail}"
            if response.status_code == 404:
                hint = (
                    "The deployment did not recognize this path. Verify the Deployment name matches "
                    "the Foundry managed-compute deployment exactly (case-sensitive) and that it is a "
                    "GlobalManagedCompute deployment, not an OpenAI-compatible serverless one."
                )
            elif response.status_code in (401, 403):
                hint = (
                    "The Foundry deployment rejected the API key. Re-copy the key from the "
                    "deployment's Endpoint tab and re-save it in Settings → Secrets."
                )
            elif response.status_code == 422:
                hint = (
                    "The deployment rejected the request body (invalid parameters). Try a supported "
                    "resolution/frame count, or reduce steps/guidance."
                )
            elif response.status_code == 429:
                hint = "Azure Foundry deployment is busy / rate limited. Wait a moment, then retry."
        except Exception:
            pass
        raise UserFacingError(
            message,
            hint=hint,
            code="AZURE_FOUNDRY_API_ERROR",
            status_code=502 if response.status_code < 500 else response.status_code,
        )
