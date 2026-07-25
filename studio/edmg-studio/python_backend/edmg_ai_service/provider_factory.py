from __future__ import annotations

from .config import Settings
from .providers.base import PlanProvider
from .providers.fallback import RuleBasedPlanner
from .providers.ollama import OllamaPlanner
from .providers.openai_compat import OpenAICompatPlanner


def build_provider(settings: Settings) -> PlanProvider:
    if settings.provider == "ollama":
        return OllamaPlanner(base_url=settings.ollama_url, model=settings.ollama_model)

    if settings.provider in ("openai_compat", "openai-compatible", "openai"):
        return OpenAICompatPlanner(
            base_url=settings.openai_compat_base_url,
            api_key=settings.openai_compat_api_key,
            model=settings.openai_compat_model,
        )

    if settings.provider in ("nemotron_cloud", "nvidia_nim", "nemotron"):
        return OpenAICompatPlanner(
            base_url=settings.nemotron_cloud_base_url,
            api_key=settings.nemotron_cloud_api_key,
            model=settings.nemotron_cloud_model,
        )

    # "none", "rule_based", or unknown provider -> safe fallback
    return RuleBasedPlanner()
