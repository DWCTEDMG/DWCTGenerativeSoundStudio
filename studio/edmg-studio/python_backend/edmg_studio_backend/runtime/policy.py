from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RuntimePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["auto", "compatibility", "performance", "pytorch_cuda", "tensorrt", "cpu"] = "auto"
    enabled: bool = True
    auto_build: bool = True
    allow_fallback: bool = True
    precision: Literal["auto", "fp32", "fp16"] = "auto"
    strict: bool = False
    cache_enabled: bool = True
    cache_limit_gb: float = Field(default=100, ge=1, le=1000, allow_inf_nan=False)
    package_path: str = ""


def load_policy(data_dir):
    from ..services.render_settings import RenderSettingsStore
    return RuntimePolicy.model_validate(RenderSettingsStore(data_dir).get()["runtime"])
