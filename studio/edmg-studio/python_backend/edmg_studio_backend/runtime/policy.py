from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RuntimePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["auto", "compatibility", "performance", "pytorch_cuda", "tensorrt", "cpu"] = "auto"
    enabled: bool = True
    device: int | None = Field(default=None, ge=0, le=63, exclude=True)
    auto_build: bool = True
    allow_fallback: bool = True
    precision: Literal["auto", "fp32", "fp16"] = "auto"
    strict: bool = False
    cache_enabled: bool = True
    cache_limit_gb: float = Field(default=100, ge=1, le=1000, allow_inf_nan=False)
    package_path: str = ""

    validation_max_abs_fp32: float = Field(default=0.0075, ge=0, le=1, allow_inf_nan=False)
    validation_mean_abs_fp32: float = Field(default=0.0005, ge=0, le=1, allow_inf_nan=False)
    validation_rmse_fp32: float = Field(default=0.0015, ge=0, le=1, allow_inf_nan=False)
    validation_p99_abs_fp32: float = Field(default=0.0025, ge=0, le=1, allow_inf_nan=False)
    validation_min_psnr_db_fp32: float = Field(default=60.0, ge=0, le=300, allow_inf_nan=False)
    validation_min_ssim_fp32: float = Field(default=0.9990, ge=-1, le=1, allow_inf_nan=False)

    validation_max_abs_fp16: float = Field(default=0.05, ge=0, le=1, allow_inf_nan=False)
    validation_mean_abs_fp16: float = Field(default=0.005, ge=0, le=1, allow_inf_nan=False)
    validation_rmse_fp16: float = Field(default=0.010, ge=0, le=1, allow_inf_nan=False)
    validation_p99_abs_fp16: float = Field(default=0.010, ge=0, le=1, allow_inf_nan=False)
    validation_min_psnr_db_fp16: float = Field(default=35.0, ge=0, le=300, allow_inf_nan=False)
    validation_min_ssim_fp16: float = Field(default=0.9950, ge=-1, le=1, allow_inf_nan=False)

    def validation_limits(self, precision: str, component: str | None = None) -> dict[str, float]:
        if precision not in {"fp32", "fp16"}:
            raise ValueError(f"Unsupported validation precision: {precision}")
        suffix = precision
        limits = {
            "max_absolute_error": getattr(self, f"validation_max_abs_{suffix}"),
            "mean_absolute_error": getattr(self, f"validation_mean_abs_{suffix}"),
            "rmse": getattr(self, f"validation_rmse_{suffix}"),
            "p99_absolute_error": getattr(self, f"validation_p99_abs_{suffix}"),
            "min_psnr_db": getattr(self, f"validation_min_psnr_db_{suffix}"),
            "min_ssim_global": getattr(self, f"validation_min_ssim_{suffix}"),
        }
        if precision == "fp16" and component == "vae_decoder":
            limits["max_absolute_error"] = max(limits["max_absolute_error"], 0.15)
        if precision == "fp16" and component == "unet":
            limits["mean_absolute_error"] = max(limits["mean_absolute_error"], 0.006)
            limits["p99_absolute_error"] = max(limits["p99_absolute_error"], 0.020)
        return limits


def load_policy(data_dir):
    from ..services.render_settings import RenderSettingsStore
    return RuntimePolicy.model_validate(RenderSettingsStore(data_dir).get()["runtime"])


class OperationRuntimePolicy(BaseModel):
    """Request-only choices; package paths and cache administration stay global."""
    model_config = ConfigDict(extra="forbid")
    mode: Literal["auto", "compatibility", "performance", "pytorch_cuda", "tensorrt", "cpu"] | None = None
    enabled: bool | None = None
    precision: Literal["auto", "fp32", "fp16"] | None = None
    allow_fallback: bool | None = None
    strict: bool | None = None
    device: int | None = Field(default=None, ge=0, le=63)


def resolve_policy(data_dir, operation=None):
    policy = load_policy(data_dir)
    override = OperationRuntimePolicy.model_validate(operation or {}).model_dump(exclude_none=True)
    effective = RuntimePolicy.model_validate({**policy.model_dump(), **override})
    # A render may opt out, but never bypass the Studio-wide disable switch.
    effective.enabled = policy.enabled and effective.enabled
    return effective


def require_tensorrt_enabled(data_dir, operation=None):
    """Explicit legacy TensorRT routes must respect the same opt-out policy."""
    from ..errors import UserFacingError
    policy = resolve_policy(data_dir, operation)
    if not policy.enabled or policy.mode in {"pytorch_cuda", "cpu"}:
        raise UserFacingError(
            "TensorRT is disabled for this render",
            hint="Choose the Internal renderer without the TensorRT bundle, or enable TensorRT in Studio settings and this render's acceleration preference.",
            code="TENSORRT_DISABLED", status_code=409,
        )
