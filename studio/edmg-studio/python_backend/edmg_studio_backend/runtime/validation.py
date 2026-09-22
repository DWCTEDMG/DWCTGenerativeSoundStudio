# TensorRT component numerical/image-statistics validation.
from __future__ import annotations

import math

VALIDATION_SCHEMA = 2

DEFAULT_LIMITS = {
    "fp32": {
        "max_absolute_error": 0.0075,
        "mean_absolute_error": 0.0005,
        "rmse": 0.0015,
        "p99_absolute_error": 0.0025,
        "min_psnr_db": 60.0,
        "min_ssim_global": 0.9990,
    },
    "fp16": {
        "max_absolute_error": 0.05,
        "mean_absolute_error": 0.005,
        "rmse": 0.010,
        "p99_absolute_error": 0.010,
        "min_psnr_db": 35.0,
        "min_ssim_global": 0.9950,
    },
}

def default_validation_limits(precision: str) -> dict[str, float]:
    try:
        return dict(DEFAULT_LIMITS[precision])
    except KeyError as exc:
        raise ValueError(f"Unsupported validation precision: {precision}") from exc

def tensor_validation_metrics(reference, actual) -> dict[str, float]:
    import torch
    ref = reference.detach().float()
    got = actual.detach().float()

    if tuple(ref.shape) != tuple(got.shape):
        raise RuntimeError(
            f"TensorRT validation shape mismatch: reference={tuple(ref.shape)} "
            f"actual={tuple(got.shape)}"
        )

    if not torch.isfinite(ref).all() or not torch.isfinite(got).all():
        raise RuntimeError("VAE validation returned nonfinite pixels")

    delta = got - ref
    absolute = delta.abs()
    flat_absolute = absolute.reshape(-1)

    max_absolute_error = float(flat_absolute.max().item())
    mean_absolute_error = float(flat_absolute.mean().item())
    mse = float((delta * delta).mean().item())
    rmse = math.sqrt(max(mse, 0.0))
    relative = absolute / ref.abs().clamp_min(1.0e-4)
    max_relative_error = float(relative.max().item())
    p99_absolute_error = float(torch.quantile(flat_absolute, 0.99).item())

    data_range = max(float((ref.max() - ref.min()).abs().item()), 1.0)
    if rmse <= 1.0e-12:
        psnr_db = 300.0
    else:
        psnr_db = min(300.0, 20.0 * math.log10(data_range / rmse))

    ref_mean = float(ref.mean().item())
    got_mean = float(got.mean().item())
    ref_centered = ref - ref_mean
    got_centered = got - got_mean
    ref_variance = float((ref_centered * ref_centered).mean().item())
    got_variance = float((got_centered * got_centered).mean().item())
    covariance = float((ref_centered * got_centered).mean().item())

    c1 = (0.01 * data_range) ** 2
    c2 = (0.03 * data_range) ** 2
    numerator = (2.0 * ref_mean * got_mean + c1) * (2.0 * covariance + c2)
    denominator = (
        (ref_mean * ref_mean + got_mean * got_mean + c1)
        * (ref_variance + got_variance + c2)
    )

    if abs(denominator) <= 1.0e-20:
        ssim_global = 1.0 if rmse <= 1.0e-12 else 0.0
    else:
        ssim_global = max(-1.0, min(1.0, numerator / denominator))

    return {
        "max_absolute_error": max_absolute_error,
        "mean_absolute_error": mean_absolute_error,
        "rmse": rmse,
        "p99_absolute_error": p99_absolute_error,
        "max_relative_error": max_relative_error,
        "psnr_db": float(psnr_db),
        "ssim_global": float(ssim_global),
    }

def aggregate_validation_metrics(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("At least one validation sample is required")
    return {
        "max_absolute_error": max(float(row["max_absolute_error"]) for row in rows),
        "mean_absolute_error": max(float(row["mean_absolute_error"]) for row in rows),
        "rmse": max(float(row["rmse"]) for row in rows),
        "p99_absolute_error": max(float(row["p99_absolute_error"]) for row in rows),
        "max_relative_error": max(float(row["max_relative_error"]) for row in rows),
        "psnr_db": min(float(row["psnr_db"]) for row in rows),
        "ssim_global": min(float(row["ssim_global"]) for row in rows),
        "samples": rows,
    }

def evaluate_validation(metrics: dict, limits: dict[str, float]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for name in (
        "max_absolute_error",
        "mean_absolute_error",
        "rmse",
        "p99_absolute_error",
    ):
        value = float(metrics[name])
        limit = float(limits[name])
        if value > limit:
            failures.append(f"{name}={value} > {limit}")

    for metric_name, limit_name in (
        ("psnr_db", "min_psnr_db"),
        ("ssim_global", "min_ssim_global"),
    ):
        value = float(metrics[metric_name])
        limit = float(limits[limit_name])
        if value < limit:
            failures.append(f"{metric_name}={value} < {limit}")

    return not failures, failures
