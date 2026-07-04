from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STABILITY_SERVICES = ("core", "ultra", "sd3")
STABILITY_SD3_MODELS = ("sd3.5-large", "sd3.5-large-turbo", "sd3.5-medium")

FIREFLY_STYLES = (
    "none", "photo", "art", "graphic", "illustration",
    "sketch", "watercolor", "pixel-art",
)
FIREFLY_CONTENT_CLASSES = ("photo", "art")

STABILITY_STYLE_PRESETS = (
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

VIDEO_GENERATION_PREFERENCES = (
    "auto",
    "local_gpu",
    "cosmos_cloud",
    "comfyui",
    "firefly_cloud",
    "imagineart_cloud",
)

DEFAULT_RENDER_PROVIDER_SETTINGS: dict[str, Any] = {
    "video": {
        "preference": "auto",
        "auto_prefer_gpu": True,
        "cosmos_fallback": True,
        "allow_proxy_renders": True,
    },
    "cosmos": {
        "enabled": True,
        "model": "cosmos3",
        "model_size": "nano",
        "steps": 50,
        "guidance_scale": 7.5,
        "num_frames": 121,
        "fps": 24.0,
        "prompt_upsampling": True,
        "base_url": "",
        "timeout_s": 600,
    },
    "firefly": {
        "enabled": False,
        "allow_auto_fallback": True,
        "custom_model_id": "",
        "style": "none",
        "content_class": "photo",
        "strength": 0.6,
        "video_enabled": False,
        "video_duration_s": 5,
    },
    "stability": {
        "enabled": False,
        "allow_auto_fallback": True,
        "service": "sd3",
        "model": "sd3.5-large-turbo",
        "style_preset": "none",
        "output_format": "png",
        "strength": 0.55,
        "cfg_scale": 6.5,
    },
    "imagineart": {
        "enabled": False,
        "allow_auto_fallback": True,
        "image_style": "imagine-turbo",
        "video_style": "kling-1.0-pro",
        "video_enabled": False,
        "timeout_s": 600,
    },
    "cuda": {
        "enabled": True,
        "allow_auto_selection": True,
        "preferred_model": "auto",
        "enable_tf32": True,
        "optimize_comfyui": True,
    },
    "directml": {
        "enabled": True,
        "allow_auto_selection": True,
        "preferred_model": "auto",
    },
}


def _config_dir(data_dir: Path) -> Path:
    p = (data_dir / "config").resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _clone_defaults() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_RENDER_PROVIDER_SETTINGS))


class RenderSettingsStore:
    def __init__(self, data_dir: Path):
        self._path = _config_dir(data_dir) / "render_providers.json"

    def get(self) -> dict[str, Any]:
        current = _read_json(self._path, default={})
        if not isinstance(current, dict):
            current = {}
        merged = _clone_defaults()
        for key, value in current.items():
            if key not in merged or not isinstance(value, dict):
                continue
            merged[key].update(value)
        return self._sanitize(merged)

    def update(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        current = self.get()
        incoming = payload if isinstance(payload, dict) else {}
        for key in ("video", "cosmos", "firefly", "stability", "imagineart", "cuda", "directml"):
            value = incoming.get(key)
            if isinstance(value, dict):
                current[key].update(value)
        cleaned = self._sanitize(current)
        _write_json(self._path, cleaned)
        return cleaned

    def _sanitize(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = _clone_defaults()

        video = payload.get("video") if isinstance(payload.get("video"), dict) else {}
        cosmos = payload.get("cosmos") if isinstance(payload.get("cosmos"), dict) else {}
        firefly = payload.get("firefly") if isinstance(payload.get("firefly"), dict) else {}
        stability = payload.get("stability") if isinstance(payload.get("stability"), dict) else {}
        imagineart = payload.get("imagineart") if isinstance(payload.get("imagineart"), dict) else {}
        cuda = payload.get("cuda") if isinstance(payload.get("cuda"), dict) else {}
        directml = payload.get("directml") if isinstance(payload.get("directml"), dict) else {}

        service = str(stability.get("service") or out["stability"]["service"]).strip().lower()
        if service not in STABILITY_SERVICES:
            service = out["stability"]["service"]

        model = str(stability.get("model") or out["stability"]["model"]).strip().lower()
        if model not in STABILITY_SD3_MODELS:
            model = out["stability"]["model"]

        style_preset = str(stability.get("style_preset") or out["stability"]["style_preset"]).strip().lower()
        if style_preset not in STABILITY_STYLE_PRESETS:
            style_preset = out["stability"]["style_preset"]

        output_format = str(stability.get("output_format") or out["stability"]["output_format"]).strip().lower()
        if output_format not in {"png", "jpeg", "webp"}:
            output_format = out["stability"]["output_format"]

        preferred_model = str(directml.get("preferred_model") or out["directml"]["preferred_model"]).strip().lower()
        if preferred_model not in {"auto", "hf_sdxl_internal", "hf_sd15_internal"}:
            preferred_model = out["directml"]["preferred_model"]

        cuda_preferred_model = str(cuda.get("preferred_model") or out["cuda"]["preferred_model"]).strip().lower()
        if cuda_preferred_model not in {"auto", "hf_sd35_medium_internal", "hf_sdxl_internal", "hf_sd15_internal"}:
            cuda_preferred_model = out["cuda"]["preferred_model"]

        video_pref = str(video.get("preference") or out["video"]["preference"]).strip().lower()
        if video_pref not in VIDEO_GENERATION_PREFERENCES:
            video_pref = out["video"]["preference"]
        out["video"] = {
            "preference": video_pref,
            "auto_prefer_gpu": bool(video.get("auto_prefer_gpu", out["video"]["auto_prefer_gpu"])),
            "cosmos_fallback": bool(video.get("cosmos_fallback", out["video"]["cosmos_fallback"])),
            "allow_proxy_renders": bool(video.get("allow_proxy_renders", out["video"]["allow_proxy_renders"])),
        }

        cosmos_model = str(cosmos.get("model") or out["cosmos"]["model"]).strip().lower()
        if cosmos_model not in {"text2world", "video2world", "cosmos3"}:
            cosmos_model = out["cosmos"]["model"]
        cosmos_model_size = str(cosmos.get("model_size") or out["cosmos"]["model_size"]).strip().lower()
        if cosmos_model_size not in {"nano", "super"}:
            cosmos_model_size = out["cosmos"]["model_size"]
        out["cosmos"] = {
            "enabled": bool(cosmos.get("enabled", out["cosmos"]["enabled"])),
            "model": cosmos_model,
            "model_size": cosmos_model_size,
            "steps": max(10, min(100, int(cosmos.get("steps", out["cosmos"]["steps"])))),
            "guidance_scale": max(1.0, min(20.0, float(cosmos.get("guidance_scale", out["cosmos"]["guidance_scale"])))),
            "num_frames": max(25, min(480, int(cosmos.get("num_frames", out["cosmos"]["num_frames"])))),
            "fps": max(1.0, min(60.0, float(cosmos.get("fps", out["cosmos"]["fps"])))),
            "prompt_upsampling": bool(cosmos.get("prompt_upsampling", out["cosmos"]["prompt_upsampling"])),
            "base_url": str(cosmos.get("base_url") or "").strip(),
            "timeout_s": max(60, min(1800, int(cosmos.get("timeout_s", out["cosmos"]["timeout_s"])))),
        }

        firefly_style = str(firefly.get("style") or out["firefly"]["style"]).strip().lower()
        if firefly_style not in FIREFLY_STYLES:
            firefly_style = out["firefly"]["style"]
        firefly_content_class = str(firefly.get("content_class") or out["firefly"]["content_class"]).strip().lower()
        if firefly_content_class not in FIREFLY_CONTENT_CLASSES:
            firefly_content_class = out["firefly"]["content_class"]

        out["firefly"] = {
            "enabled": bool(firefly.get("enabled", out["firefly"]["enabled"])),
            "allow_auto_fallback": bool(firefly.get("allow_auto_fallback", out["firefly"]["allow_auto_fallback"])),
            "custom_model_id": str(firefly.get("custom_model_id") or "").strip(),
            "style": firefly_style,
            "content_class": firefly_content_class,
            "strength": max(0.1, min(1.0, float(firefly.get("strength", out["firefly"]["strength"])))),
            "video_enabled": bool(firefly.get("video_enabled", out["firefly"]["video_enabled"])),
            "video_duration_s": max(1, min(10, int(firefly.get("video_duration_s", out["firefly"]["video_duration_s"])))),
        }
        out["stability"] = {
            "enabled": bool(stability.get("enabled", out["stability"]["enabled"])),
            "allow_auto_fallback": bool(
                stability.get("allow_auto_fallback", out["stability"]["allow_auto_fallback"])
            ),
            "service": service,
            "model": model,
            "style_preset": style_preset,
            "output_format": output_format,
            "strength": max(0.1, min(1.0, float(stability.get("strength", out["stability"]["strength"])))),
            "cfg_scale": max(1.0, min(10.0, float(stability.get("cfg_scale", out["stability"]["cfg_scale"])))),
        }

        from .imagineart_platform import IMAGINEART_IMAGE_STYLES, IMAGINEART_VIDEO_STYLES

        imagineart_image_style = str(
            imagineart.get("image_style") or out["imagineart"]["image_style"]
        ).strip().lower()
        if imagineart_image_style not in IMAGINEART_IMAGE_STYLES:
            imagineart_image_style = out["imagineart"]["image_style"]
        imagineart_video_style = str(
            imagineart.get("video_style") or out["imagineart"]["video_style"]
        ).strip().lower()
        if imagineart_video_style not in IMAGINEART_VIDEO_STYLES:
            imagineart_video_style = out["imagineart"]["video_style"]
        out["imagineart"] = {
            "enabled": bool(imagineart.get("enabled", out["imagineart"]["enabled"])),
            "allow_auto_fallback": bool(
                imagineart.get("allow_auto_fallback", out["imagineart"]["allow_auto_fallback"])
            ),
            "image_style": imagineart_image_style,
            "video_style": imagineart_video_style,
            "video_enabled": bool(imagineart.get("video_enabled", out["imagineart"]["video_enabled"])),
            "timeout_s": max(60, min(1800, int(imagineart.get("timeout_s", out["imagineart"]["timeout_s"])))),
        }
        out["cuda"] = {
            "enabled": bool(cuda.get("enabled", out["cuda"]["enabled"])),
            "allow_auto_selection": bool(
                cuda.get("allow_auto_selection", out["cuda"]["allow_auto_selection"])
            ),
            "preferred_model": cuda_preferred_model,
            "enable_tf32": bool(cuda.get("enable_tf32", out["cuda"]["enable_tf32"])),
            "optimize_comfyui": bool(cuda.get("optimize_comfyui", out["cuda"]["optimize_comfyui"])),
        }
        out["directml"] = {
            "enabled": bool(directml.get("enabled", out["directml"]["enabled"])),
            "allow_auto_selection": bool(
                directml.get("allow_auto_selection", out["directml"]["allow_auto_selection"])
            ),
            "preferred_model": preferred_model,
        }
        return out
