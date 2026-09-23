from __future__ import annotations

import math
import torch

from edmg_studio_backend.runtime.policy import RuntimePolicy
from edmg_studio_backend.runtime.validation import (
    aggregate_validation_metrics,
    default_validation_limits,
    evaluate_validation,
    tensor_validation_metrics,
)

def test_identical_tensors_produce_finite_perfect_receipt():
    reference = torch.linspace(-1, 1, 3 * 16 * 16).reshape(1, 3, 16, 16)
    metrics = tensor_validation_metrics(reference, reference.clone())
    assert metrics["max_absolute_error"] == 0
    assert metrics["mean_absolute_error"] == 0
    assert metrics["rmse"] == 0
    assert math.isfinite(metrics["psnr_db"])
    assert metrics["psnr_db"] == 300
    assert metrics["ssim_global"] == 1

def test_fp32_profile_accepts_small_isolated_0054_outlier():
    generator = torch.Generator().manual_seed(1729)
    reference = torch.randn((1, 3, 64, 64), generator=generator) * 0.25
    actual = reference.clone()
    actual.reshape(-1)[17] += 0.005408287
    row = {"seed": 1729, **tensor_validation_metrics(reference, actual)}
    receipt = aggregate_validation_metrics([row])
    passed, failures = evaluate_validation(
        receipt,
        default_validation_limits("fp32"),
    )
    assert passed, failures
    assert receipt["max_absolute_error"] > 0.005


def test_fp16_profile_accepts_isolated_decoder_outlier_with_strict_aggregate_quality():
    generator = torch.Generator().manual_seed(42)
    reference = torch.randn((1, 3, 64, 64), generator=generator)
    actual = reference.clone()
    actual.reshape(-1)[17] += 0.125
    row = {"seed": 42, **tensor_validation_metrics(reference, actual)}
    receipt = aggregate_validation_metrics([row])
    passed, failures = evaluate_validation(
        receipt,
        RuntimePolicy().validation_limits("fp16", "vae_decoder"),
    )
    assert passed, failures
    assert receipt["max_absolute_error"] > default_validation_limits("fp16")["max_absolute_error"]
    assert receipt["p99_absolute_error"] < 0.01


def test_fp16_unet_profile_accepts_narrow_quantization_tail_but_rejects_broad_drift():
    policy = RuntimePolicy()
    generator = torch.Generator().manual_seed(42)
    reference = torch.randn((1, 4, 64, 64), generator=generator)
    narrow = reference.clone()
    narrow.reshape(-1)[:328] += 0.0185
    narrow_receipt = aggregate_validation_metrics([
        {"seed": 42, **tensor_validation_metrics(reference, narrow)},
    ])
    passed, failures = evaluate_validation(
        narrow_receipt,
        policy.validation_limits("fp16", "unet"),
    )
    assert passed, failures
    assert narrow_receipt["p99_absolute_error"] > default_validation_limits("fp16")["p99_absolute_error"]

    broad_receipt = aggregate_validation_metrics([
        {"seed": 42, **tensor_validation_metrics(reference, reference + 0.0125)},
    ])
    passed, failures = evaluate_validation(
        broad_receipt,
        policy.validation_limits("fp16", "unet"),
    )
    assert not passed
    assert any(
        "mean_absolute_error" in failure or "rmse" in failure
        for failure in failures
    )


def test_validation_rejects_broad_fp32_drift():
    generator = torch.Generator().manual_seed(42)
    reference = torch.randn((1, 3, 32, 32), generator=generator)
    actual = reference + 0.01
    row = {"seed": 42, **tensor_validation_metrics(reference, actual)}
    receipt = aggregate_validation_metrics([row])
    passed, failures = evaluate_validation(
        receipt,
        default_validation_limits("fp32"),
    )
    assert not passed
    assert failures
    assert any(
        "mean_absolute_error" in failure
        or "rmse" in failure
        or "p99_absolute_error" in failure
        for failure in failures
    )

def test_aggregate_uses_worst_case_across_fixed_seeds():
    reference = torch.linspace(-1, 1, 1024).reshape(1, 1, 32, 32)
    rows = []
    for seed, delta in ((1729, 0.0001), (42, 0.0002), (7, 0.0003)):
        actual = reference + delta
        rows.append({"seed": seed, **tensor_validation_metrics(reference, actual)})
    receipt = aggregate_validation_metrics(rows)
    assert len(receipt["samples"]) == 3
    assert receipt["max_absolute_error"] >= rows[-1]["max_absolute_error"]
    assert receipt["psnr_db"] <= rows[0]["psnr_db"]
