"""Request-scoped creative planning without changing global provider settings."""
from __future__ import annotations

import base64
import subprocess
from dataclasses import replace
from pathlib import Path


def plan_with_provider(payload: dict, *, provider: str, model: str | None,
                       audio_path: Path | None = None) -> dict:
    from edmg_ai_service.config import Settings as AiSettings
    from edmg_ai_service.provider_factory import build_provider
    from edmg_ai_service.schemas import PlanRequest
    from ..config import Settings
    from .secrets import SecretStore

    settings = AiSettings()
    selected = settings.provider if provider == "configured" else provider
    overrides = {"provider": selected}
    keys = SecretStore(Settings().data_dir)
    overrides["openai_compat_api_key"] = settings.openai_compat_api_key or keys.get("openai_compat_api_key")
    overrides["nemotron_cloud_api_key"] = settings.nemotron_cloud_api_key or keys.get("nvidia_api_key") or keys.get("openai_compat_api_key")
    if model and model.strip():
        field = {"ollama": "ollama_model", "nemotron_cloud": "nemotron_cloud_model",
                 "nvidia_nim": "nemotron_cloud_model", "nemotron": "nemotron_cloud_model"}.get(selected, "openai_compat_model")
        overrides[field] = model.strip()
    planner = build_provider(replace(settings, **overrides))
    request = PlanRequest(**payload)
    if audio_path is not None:
        from edmg_ai_service.providers.openai_compat import OpenAICompatPlanner
        if not isinstance(planner, OpenAICompatPlanner):
            raise ValueError("Direct audio requires an audio-capable OpenAI-compatible endpoint. Select analyzed audio for this provider.")
        # A compact full-track WAV preserves timing and avoids sending a studio master.
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(audio_path), "-vn", "-ac", "1",
             "-ar", "16000", "-c:a", "pcm_s16le", "-f", "wav", "pipe:1"],
            capture_output=True, check=True, timeout=180,
        )
        request.input_audio = {"data": base64.b64encode(result.stdout).decode("ascii"), "format": "wav"}
    response = planner.plan(request)
    if response.provider == "rule_based" and selected not in {"local", "rule_based", "none"}:
        raise RuntimeError("The selected provider did not return a valid scene plan. Check its connection and model in Settings; your existing draft is preserved.")
    return response.model_dump()
