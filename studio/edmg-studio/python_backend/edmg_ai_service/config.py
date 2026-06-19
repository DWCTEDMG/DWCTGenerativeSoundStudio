from __future__ import annotations

import os
from dataclasses import dataclass

_NVIDIA_NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
_NEMOTRON_ULTRA_MODEL = "nvidia/llama-3.1-nemotron-ultra-253b-v1"


@dataclass(frozen=True)
class Settings:
    # planning provider — defaults to NVIDIA Nemotron Ultra cloud
    provider: str = os.getenv("EDMG_AI_PROVIDER", "nemotron_cloud").strip().lower()

    # ollama
    ollama_url: str = os.getenv("EDMG_AI_OLLAMA_URL", "http://127.0.0.1:11434").strip()
    ollama_model: str = os.getenv("EDMG_AI_OLLAMA_MODEL", "qwen3:8b").strip()

    # openai-compatible (generic)
    openai_compat_base_url: str = os.getenv("EDMG_AI_OPENAI_COMPAT_BASE_URL", "http://127.0.0.1:8000").strip()
    openai_compat_api_key: str | None = (os.getenv("EDMG_AI_OPENAI_COMPAT_API_KEY") or None)
    openai_compat_model: str = os.getenv("EDMG_AI_OPENAI_COMPAT_MODEL", "qwen3-8b").strip()

    # NVIDIA NIM / Nemotron Ultra cloud
    nemotron_cloud_base_url: str = os.getenv("EDMG_AI_NVIDIA_BASE_URL", _NVIDIA_NIM_BASE_URL).strip()
    nemotron_cloud_model: str = os.getenv("EDMG_AI_NVIDIA_MODEL", _NEMOTRON_ULTRA_MODEL).strip()
    nemotron_cloud_api_key: str | None = (
        os.getenv("EDMG_AI_NVIDIA_API_KEY") or os.getenv("EDMG_AI_OPENAI_COMPAT_API_KEY") or None
    )
