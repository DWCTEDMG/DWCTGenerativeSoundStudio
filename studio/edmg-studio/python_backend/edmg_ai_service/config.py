from __future__ import annotations

import os
from dataclasses import dataclass

_NVIDIA_NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
_NEMOTRON_ULTRA_MODEL = "nvidia/llama-3.1-nemotron-ultra-253b-v1"
_DIFFUSIONGEMMA_MODEL = "google/diffusiongemma-26B-A4B-it"
_NVIDIA_PROMPT_MODEL_PRESETS = (
    {
        "id": "nemotron_ultra",
        "label": "Nemotron Ultra 253B",
        "model": _NEMOTRON_ULTRA_MODEL,
        "family": "nemotron",
        "description": "High-quality creative planning and storyboard reasoning through NVIDIA's OpenAI-compatible API.",
    },
    {
        "id": "diffusiongemma",
        "label": "DiffusionGemma 26B A4B",
        "model": _DIFFUSIONGEMMA_MODEL,
        "family": "diffusiongemma",
        "description": "Fast parallel text generation for planner and prompt refinement on NVIDIA NIM or vLLM endpoints.",
    },
)


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
