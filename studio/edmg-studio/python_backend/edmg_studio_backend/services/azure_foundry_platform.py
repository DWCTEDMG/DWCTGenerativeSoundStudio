"""Optional Cosmos3 video endpoint. Azure routing must be supplied explicitly.

Implements NVIDIA's vLLM-Omni videos/sync form-data contract, not chat
completions. No Azure-specific video path is inferred from deployment metadata.
"""
from __future__ import annotations

import io
import json
import math
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import requests
from PIL import Image

from ..errors import UserFacingError
from .ffmpeg import ensure_ffmpeg, ensure_ffprobe


def validate_azure_url(value: str) -> str:
    value = str(value or "").strip().rstrip("/")
    if not value:
        return ""
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or not parsed.hostname.endswith((".services.ai.azure.com", ".openai.azure.com",
                                               ".inference.ml.azure.com"))):
        raise UserFacingError("Enter an HTTPS Azure inference URL without credentials or query parameters.",
                              code="AZURE_FOUNDRY_INVALID_ENDPOINT", status_code=400)
    return value


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
    def __init__(self, api_key: str = "", endpoint_url: str = "", deployment_name: str = "",
                 timeout_s: float = 600, video_endpoint_url: str = "", ffmpeg_path: str = "ffmpeg"):
        self.api_key = str(api_key or "").strip()
        self.endpoint_url = validate_azure_url(endpoint_url)
        self.deployment_name = str(deployment_name or "").strip()
        self.video_endpoint_url = validate_azure_url(video_endpoint_url)
        self.timeout_s = float(timeout_s)
        self.ffmpeg_path = ffmpeg_path
        if self.video_endpoint_url and self.endpoint_url:
            if urlsplit(self.video_endpoint_url).netloc != urlsplit(self.endpoint_url).netloc:
                raise UserFacingError("The video URL must use the same Azure resource as the connection URL.",
                                      code="AZURE_FOUNDRY_INVALID_ENDPOINT", status_code=400)
        if self.video_endpoint_url and "/chat/completions" in self.video_endpoint_url:
            raise UserFacingError("Chat completions is not a video generation endpoint.",
                                  hint="Copy the video request URL from the deployment's video sample.",
                                  code="AZURE_FOUNDRY_CHAT_ENDPOINT", status_code=400)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise UserFacingError("Azure Foundry API key is not set.",
                                  hint="Save it in Settings → Secrets as azure_foundry_api_key.",
                                  code="AZURE_FOUNDRY_NO_API_KEY", status_code=400)
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "video/mp4"}

    def _endpoint(self) -> str:
        if not self.endpoint_url or not self.deployment_name or not self.video_endpoint_url:
            raise UserFacingError("Azure video generation is not configured.",
                                  hint="Set the resource URL, deployment name, and explicit video request URL in Settings → Azure Cosmos3-Super.",
                                  code="AZURE_FOUNDRY_NOT_CONFIGURED", status_code=400)
        return self.video_endpoint_url

    def check_connection(self) -> dict:
        """Read-only authentication check. A model listing is not video qualification."""
        if not self.endpoint_url:
            raise UserFacingError("Set the Azure resource URL first.", code="AZURE_FOUNDRY_NOT_CONFIGURED", status_code=400)
        base = self.endpoint_url
        if base.endswith("/chat/completions"):
            base = base.removesuffix("/chat/completions")
        elif not base.endswith("/v1"):
            base += "/openai/v1"
        try:
            response = requests.get(base + "/models", headers=self._headers(), timeout=(10, 20), allow_redirects=False)
            if response.status_code != 200:
                self._raise_api_error(response)
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                raise ValueError("Not a models response")
        except requests.RequestException as exc:
            raise UserFacingError("Azure connection check failed.", code="AZURE_FOUNDRY_UNREACHABLE", status_code=502) from exc
        except ValueError as exc:
            raise UserFacingError("Azure did not return a model listing.", code="AZURE_FOUNDRY_INVALID_RESPONSE", status_code=502) from exc
        names = [str(item.get("id")) for item in data["data"] if isinstance(item, dict)]
        return {"connected": True, "deployment_listed": self.deployment_name in names,
                "video_configured": bool(self.video_endpoint_url), "video_verified": False,
                "message": "Azure authentication and model listing succeeded. Video generation remains unverified until a clip passes media validation."}

    def text_to_video(self, *, prompt: str, out_path: Path,
                      negative_prompt: str = "blurry, low quality, text, watermark, logo",
                      width: int = 1280, height: int = 720, fps: float = 24,
                      num_frames: int = 121, steps: int = 50, guidance_scale: float = 7,
                      seed: int | None = None) -> AzureFoundryVideoResult:
        return self._generate(prompt=prompt, out_path=out_path, negative_prompt=negative_prompt,
                              width=width, height=height, fps=fps, num_frames=num_frames,
                              steps=steps, guidance_scale=guidance_scale, seed=seed)

    def image_to_video(self, *, image: Image.Image, **kwargs) -> AzureFoundryVideoResult:
        return self._generate(image=image, **kwargs)

    def _generate(self, *, prompt: str, out_path: Path, negative_prompt: str = "",
                  width: int = 1280, height: int = 720, fps: float = 24,
                  num_frames: int = 121, steps: int = 50, guidance_scale: float = 7,
                  seed: int | None = None, image: Image.Image | None = None) -> AzureFoundryVideoResult:
        endpoint = self._endpoint()
        headers = self._headers()
        # Check local validation tools before consuming hosted inference.
        ffmpeg = ensure_ffmpeg(self.ffmpeg_path)
        ffprobe = ensure_ffprobe(self.ffmpeg_path)
        if not (5 <= int(num_frames) <= 400 and 1 <= float(fps) <= 60 and math.isfinite(float(fps))):
            raise UserFacingError("Cosmos video requires 5–400 frames and 1–60 fps.", code="AZURE_FOUNDRY_PARAMETERS", status_code=400)
        body = {"model": self.deployment_name, "prompt": prompt, "negative_prompt": negative_prompt,
                "size": f"{width}x{height}", "num_frames": str(num_frames), "fps": str(fps),
                "num_inference_steps": str(max(1, min(100, int(steps)))),
                "guidance_scale": str(max(1, min(7, float(guidance_scale)))),
                "max_sequence_length": "4096", "flow_shift": "10.0",
                "extra_params": json.dumps({"use_resolution_template": False,
                                            "use_duration_template": False, "guardrails": True})}
        if seed is not None:
            body["seed"] = str(max(0, int(seed)))
        files = None
        if image is not None:
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="PNG")
            files = {"input_reference": ("reference.png", buffer.getvalue(), "image/png")}
        try:
            response = requests.post(endpoint, headers=headers, data=body, files=files,
                                     timeout=(30, self.timeout_s), allow_redirects=False, stream=True)
        except requests.Timeout as exc:
            raise UserFacingError("Azure video generation timed out.", code="AZURE_FOUNDRY_TIMEOUT", status_code=504) from exc
        except requests.RequestException as exc:
            raise UserFacingError("Could not reach the Azure video endpoint.", code="AZURE_FOUNDRY_UNREACHABLE", status_code=502) from exc
        with response:
            if response.status_code != 200:
                self._raise_api_error(response)
            if response.headers.get("Content-Type", "").split(";", 1)[0].lower() not in {"video/mp4", "application/octet-stream"}:
                raise UserFacingError("Azure returned no MP4 video.",
                                      hint="This adapter requires the synchronous videos/sync contract. Verify the deployment's video sample URL.",
                                      code="AZURE_FOUNDRY_NO_VIDEO", status_code=502)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=out_path.parent, suffix=".mp4", delete=False) as output:
                    temporary = Path(output.name)
                    total = 0
                    for chunk in response.iter_content(1024 * 1024):
                        total += len(chunk)
                        if total > 1024 * 1024 * 1024:
                            raise ValueError("Video exceeds 1 GiB limit")
                        output.write(chunk)
                metadata = self._validate_video(temporary, ffmpeg, ffprobe, width, height, num_frames, fps)
                os.replace(temporary, out_path)
            except (ValueError, KeyError, TypeError, ZeroDivisionError, subprocess.SubprocessError, OSError, requests.RequestException) as exc:
                raise UserFacingError("Azure video failed download or media validation.",
                                      hint="The clip was not published. Verify the supported resolution, duration, and frame rate.",
                                      code="AZURE_FOUNDRY_INVALID_VIDEO", status_code=502) from exc
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return AzureFoundryVideoResult(video_path=out_path, model=self.deployment_name, seed=seed, **metadata)

    @staticmethod
    def _validate_video(path, ffmpeg, ffprobe, width, height, frames, fps) -> dict:
        probe = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-count_frames",
                                "-show_entries", "stream=width,height,avg_frame_rate,nb_read_frames,duration",
                                "-of", "json", str(path)], capture_output=True, text=True, timeout=120, check=True)
        streams = json.loads(probe.stdout).get("streams") or []
        if not streams:
            raise ValueError("No video stream")
        stream = streams[0]
        numerator, denominator = stream["avg_frame_rate"].split("/")
        actual_fps = float(numerator) / float(denominator)
        actual_frames = int(stream["nb_read_frames"])
        duration = float(stream["duration"])
        if (int(stream["width"]) != width or int(stream["height"]) != height or actual_frames != frames
                or abs(actual_fps - fps) > 0.01 or abs(duration - frames / fps) > 1 / fps + 0.01):
            raise ValueError("Video differs from requested dimensions, frames, fps, or duration")
        subprocess.run([ffmpeg, "-v", "error", "-xerror", "-i", str(path), "-map", "0:v:0", "-f", "null", "-"],
                       capture_output=True, timeout=180, check=True)
        return {"width": width, "height": height, "frames": actual_frames, "fps": actual_fps, "duration_s": duration}

    @staticmethod
    def _raise_api_error(response) -> None:
        status = response.status_code
        hint = ("Save a valid Azure API key in Settings → Secrets." if status in (401, 403) else
                "Azure did not recognize the video route. Check the deployment's video sample URL." if status == 404 else
                "Azure is busy. Retry later." if status == 429 else
                "Check the deployment's supported video request contract and parameters.")
        # Never echo remote response bodies: they may contain credentials or signed URLs.
        raise UserFacingError(f"Azure request failed (HTTP {status}).", hint=hint,
                              code="AZURE_FOUNDRY_API_ERROR", status_code=502)
