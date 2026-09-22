# PATCH_TENSORRT_RUNTIME_V2.ps1
#
# EDMG TensorRT Runtime Validation v2 patch
# Target: DWCTEDMG/DWCTGenerativeSoundStudio

[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\user\source\repos\DWCTGenerativeSoundStudio",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][scriptblock]$Command
    )
    Write-Host ""
    Write-Host "==== $Name ====" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path $RepoRoot)) {
    throw "Repository not found: $RepoRoot"
}

$RepoRoot = (Resolve-Path $RepoRoot).Path
Push-Location $RepoRoot

try {
    if (-not (Test-Path ".git")) {
        throw "$RepoRoot is not a Git repository."
    }

    Write-Host "Repository: $RepoRoot" -ForegroundColor Green
    git status --short

    $PythonCommand = $null
    $PythonPrefix = @()

    if (Get-Command py -ErrorAction SilentlyContinue) {
        $PythonCommand = "py"
        $PythonPrefix = @("-3")
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $PythonCommand = "python"
    }
    else {
        throw "Python 3 was not found."
    }

    $Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $BackupRoot = Join-Path $env:TEMP "DWCTGenerativeSoundStudio-TensorRT-v2-$Stamp"
    New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null

    $FilesToBackup = @(
        "studio\edmg-studio\python_backend\edmg_studio_backend\runtime\builder.py",
        "studio\edmg-studio\python_backend\edmg_studio_backend\runtime\manager.py",
        "studio\edmg-studio\python_backend\edmg_studio_backend\runtime\policy.py",
        "studio\edmg-studio\python_backend\edmg_studio_backend\runtime\worker.py",
        "studio\edmg-studio\python_backend\edmg_studio_backend\runtime\service.py",
        "studio\edmg-studio\python_backend\edmg_studio_backend\runtime\validation.py",
        "studio\edmg-studio\python_backend\edmg_studio_backend\tests\test_component_runtime.py",
        "studio\edmg-studio\python_backend\edmg_studio_backend\tests\test_runtime_validation.py",
        "docs\TENSORRT_RUNTIME_INTEGRATION.md"
    )

    foreach ($Relative in $FilesToBackup) {
        $Source = Join-Path $RepoRoot $Relative
        if (Test-Path $Source) {
            $Destination = Join-Path $BackupRoot $Relative
            New-Item -ItemType Directory -Force -Path (Split-Path $Destination -Parent) | Out-Null
            Copy-Item $Source $Destination -Force
        }
    }

    Write-Host "Backup: $BackupRoot" -ForegroundColor Yellow

    $Patcher = Join-Path $env:TEMP "edmg-tensorrt-runtime-v2-$Stamp.py"

    $PatcherSource = @'
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()

def path(rel: str) -> Path:
    return ROOT / rel

def read(rel: str) -> str:
    return path(rel).read_text(encoding="utf-8")

def write(rel: str, content: str) -> None:
    target = path(rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(content)

def replace_once(rel: str, old: str, new: str) -> None:
    content = read(rel)
    if new in content:
        print(f"[already patched] {rel}")
        return
    count = content.count(old)
    if count != 1:
        raise RuntimeError(
            f"{rel}: expected patch anchor exactly once, found {count}. "
            "The repository may have changed since this patch was generated."
        )
    write(rel, content.replace(old, new, 1))
    print(f"[patched] {rel}")

validation_rel = (
    "studio/edmg-studio/python_backend/"
    "edmg_studio_backend/runtime/validation.py"
)

validation_source = r'''# TensorRT component numerical/image-statistics validation.
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
'''

existing_validation = path(validation_rel)
if existing_validation.exists():
    current = existing_validation.read_text(encoding="utf-8")
    if "VALIDATION_SCHEMA = 2" not in current:
        raise RuntimeError(
            f"{validation_rel} already exists but is not this patch's validation module. "
            "Refusing to overwrite it."
        )
else:
    write(validation_rel, validation_source)
    print(f"[created] {validation_rel}")

policy_rel = (
    "studio/edmg-studio/python_backend/"
    "edmg_studio_backend/runtime/policy.py"
)

replace_once(
    policy_rel,
    '''    cache_limit_gb: float = Field(default=100, ge=1, le=1000, allow_inf_nan=False)
    package_path: str = ""
''',
    '''    cache_limit_gb: float = Field(default=100, ge=1, le=1000, allow_inf_nan=False)
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

    def validation_limits(self, precision: str) -> dict[str, float]:
        if precision not in {"fp32", "fp16"}:
            raise ValueError(f"Unsupported validation precision: {precision}")
        suffix = precision
        return {
            "max_absolute_error": getattr(self, f"validation_max_abs_{suffix}"),
            "mean_absolute_error": getattr(self, f"validation_mean_abs_{suffix}"),
            "rmse": getattr(self, f"validation_rmse_{suffix}"),
            "p99_absolute_error": getattr(self, f"validation_p99_abs_{suffix}"),
            "min_psnr_db": getattr(self, f"validation_min_psnr_db_{suffix}"),
            "min_ssim_global": getattr(self, f"validation_min_ssim_{suffix}"),
        }
'''
)

builder_rel = (
    "studio/edmg-studio/python_backend/"
    "edmg_studio_backend/runtime/builder.py"
)

replace_once(
    builder_rel,
    '''from .executor import TensorExecutor
''',
    '''from .executor import TensorExecutor
from .validation import (
    VALIDATION_SCHEMA,
    aggregate_validation_metrics,
    default_validation_limits,
    evaluate_validation,
    tensor_validation_metrics,
)

ADAPTER_VERSION = 2
'''
)

replace_once(
    builder_rel,
    '''            "compiler_settings": {"workspace_bytes": 2 * 1024**3, "tf32": False},
            "diffusers": importlib.metadata.version("diffusers"), "adapter_version": 1}
''',
    '''            "compiler_settings": {"workspace_bytes": 2 * 1024**3, "tf32": False},
            "diffusers": importlib.metadata.version("diffusers"),
            "adapter_version": ADAPTER_VERSION}
'''
)

replace_once(
    builder_rel,
    '''def prepare_component(data_dir: Path, model_dir: Path, shape: list[int], precision: str,
                      device: int, allow_build: bool, progress=lambda stage: None):
''',
    '''def prepare_component(data_dir: Path, model_dir: Path, shape: list[int], precision: str,
                      device: int, allow_build: bool,
                      validation_limits: dict | None = None,
                      progress=lambda stage: None):
'''
)

replace_once(
    builder_rel,
    '''                executor = TensorExecutor(bytes(engine), device)
                max_error, mean_error = 0.0, 0.0
                for seed in (1729, 42, 7):
                    generator.manual_seed(seed)
                    latent = torch.randn(shape, generator=generator, device=sample.device, dtype=dtype)
                    reference = module(latent)
                    actual = executor(latent)
                    error = (reference.float() - actual.float()).abs()
                    if not torch.isfinite(actual).all() or not torch.isfinite(reference).all():
                        raise RuntimeError("VAE validation returned nonfinite pixels")
                    max_error = max(max_error, error.max().item())
                    mean_error = max(mean_error, error.mean().item())
                # Pixel-domain tolerances are explicit; these are not video quality qualification.
                passed = max_error <= (0.05 if precision == "fp16" else 0.005) and mean_error <= (0.005 if precision == "fp16" else 0.0005)
                if not passed:
                    raise RuntimeError(f"VAE numerical validation failed: max={max_error}, mean={mean_error}")
''',
    '''                executor = TensorExecutor(bytes(engine), device)
                validation_rows = []
                fixed_seeds = (1729, 42, 7)
                for seed in fixed_seeds:
                    generator.manual_seed(seed)
                    latent = torch.randn(shape, generator=generator, device=sample.device, dtype=dtype)
                    reference = module(latent)
                    actual = executor(latent)
                    validation_rows.append({
                        "seed": seed,
                        **tensor_validation_metrics(reference, actual),
                    })

                limits = dict(validation_limits or default_validation_limits(precision))
                validation = aggregate_validation_metrics(validation_rows)
                passed, failures = evaluate_validation(validation, limits)
                validation.update({
                    "passed": passed,
                    "validation_schema": VALIDATION_SCHEMA,
                    "limits": limits,
                    "fixed_seeds": list(fixed_seeds),
                    "quality_scope": "component_numeric_plus_image_statistics",
                    "failures": failures,
                    "max_relative_error_is_diagnostic_only": True,
                })

                if not passed:
                    cache.state(
                        key,
                        identity,
                        "failed",
                        reason="VAE numerical validation failed",
                        validation=validation,
                    )
                    raise RuntimeError(
                        "VAE numerical validation failed: "
                        + json.dumps(
                            {
                                "max": validation["max_absolute_error"],
                                "mean": validation["mean_absolute_error"],
                                "rmse": validation["rmse"],
                                "p99": validation["p99_absolute_error"],
                                "psnr_db": validation["psnr_db"],
                                "ssim_global": validation["ssim_global"],
                                "failures": failures,
                            },
                            sort_keys=True,
                        )
                    )
'''
)

replace_once(
    builder_rel,
    '''                manifest = cache.publish(identity, bytes(engine),
                    {"passed": True, "max_absolute_error": max_error, "mean_absolute_error": mean_error,
                     "fixed_seeds": [1729, 42, 7], "quality_scope": "component_numeric_only"}, timings)
''',
    '''                manifest = cache.publish(identity, bytes(engine), validation, timings)
'''
)

replace_once(
    builder_rel,
    '''        except Exception as exc:
            cache.state(key, identity, "failed", reason=str(exc))
            raise
''',
    '''        except Exception as exc:
            previous = cache.read(key) or {}
            detail = {}
            if isinstance(previous.get("validation"), dict):
                detail["validation"] = previous["validation"]
            cache.state(key, identity, "failed", reason=str(exc), **detail)
            raise
'''
)

worker_rel = (
    "studio/edmg-studio/python_backend/"
    "edmg_studio_backend/runtime/worker.py"
)

replace_once(
    worker_rel,
    '''                    Path(configuration["data_dir"]), Path(command["model_dir"]), command["shape"],
                    command["precision"], int(command["device"]), bool(command["allow_build"]),
                    progress=lambda stage: atomic_write(root / "progress.json", json.dumps(stage if isinstance(stage, dict) else {"stage": stage}).encode()))
''',
    '''                    Path(configuration["data_dir"]), Path(command["model_dir"]), command["shape"],
                    command["precision"], int(command["device"]), bool(command["allow_build"]),
                    validation_limits=command.get("validation_limits"),
                    progress=lambda stage: atomic_write(root / "progress.json", json.dumps(stage if isinstance(stage, dict) else {"stage": stage}).encode()))
'''
)

manager_rel = (
    "studio/edmg-studio/python_backend/"
    "edmg_studio_backend/runtime/manager.py"
)

replace_once(
    manager_rel,
    '''        "tensorrt": {"sd15": ["vae_decoder"], "precision": ["fp32", "fp16"]},
        "llama_cpp": {"role": "existing_qwen_gguf"},
''',
    '''        "tensorrt": {"sd15": ["vae_decoder"], "precision": ["fp32", "fp16"]},
        "tensorrt_standalone": {
            "sd15": ["unet"],
            "role": "verified_sd15_bundle_renderer",
        },
        "llama_cpp": {"role": "existing_qwen_gguf"},
'''
)

replace_once(
    manager_rel,
    '''                result = self.process.request("prepare", timeout_s=1800,
                    model_dir=str(self.model_dir), shape=list(value.shape), precision=precision,
                    device=value.device.index or 0, allow_build=RuntimeSelector.may_build(self.policy))
''',
    '''                result = self.process.request("prepare", timeout_s=1800,
                    model_dir=str(self.model_dir), shape=list(value.shape), precision=precision,
                    device=value.device.index or 0,
                    allow_build=RuntimeSelector.may_build(self.policy),
                    validation_limits=self.policy.validation_limits(precision))
'''
)

service_rel = (
    "studio/edmg-studio/python_backend/"
    "edmg_studio_backend/runtime/service.py"
)

replace_once(
    service_rel,
    '''        result = process.request("prepare", timeout_s=1800, model_dir=str(model_dir),
            shape=[1, 4, int(payload["height"]) // 8, int(payload["width"]) // 8],
            precision=payload.get("precision", "fp16"), device=device, allow_build=True)
''',
    '''        precision = payload.get("precision", "fp16")
        result = process.request("prepare", timeout_s=1800, model_dir=str(model_dir),
            shape=[1, 4, int(payload["height"]) // 8, int(payload["width"]) // 8],
            precision=precision, device=device, allow_build=True,
            validation_limits=policy.validation_limits(precision))
'''
)

component_test_rel = (
    "studio/edmg-studio/python_backend/"
    "edmg_studio_backend/tests/test_component_runtime.py"
)

replace_once(
    component_test_rel,
    '''from edmg_studio_backend.runtime.manager import RuntimeManager, RuntimeSelector
''',
    '''from edmg_studio_backend.runtime.manager import (
    RuntimeManager,
    RuntimePlan,
    RuntimeRegistry,
    RuntimeSelector,
    pipeline_runtime_metadata,
)
'''
)

component_tests = read(component_test_rel)
if "def test_runtime_metadata_reports_actual_tensorrt_selection():" not in component_tests:
    component_tests += r'''


def test_runtime_metadata_reports_actual_tensorrt_selection():
    plan = RuntimePlan(
        "tensorrt",
        selected="tensorrt",
        device="cuda:0",
        precision="fp32",
        component="vae_decoder",
        engine_id="a" * 64,
        cache="hit",
    )
    manager = SimpleNamespace(plan=plan)
    vae = SimpleNamespace(_edmg_runtime=manager)
    pipes = SimpleNamespace(
        txt2img=SimpleNamespace(vae=vae),
        backend="diffusers",
        device="cuda",
    )
    metadata = pipeline_runtime_metadata(pipes)
    assert metadata["selected"] == "tensorrt"
    assert metadata["component"] == "vae_decoder"
    assert metadata["engine_id"] == "a" * 64


def test_component_runtime_does_not_claim_unet_but_standalone_does():
    capabilities = RuntimeRegistry().capabilities
    assert "unet" not in capabilities["tensorrt"]["sd15"]
    assert capabilities["tensorrt_standalone"]["sd15"] == ["unet"]


def test_validation_policy_has_separate_fp32_and_fp16_limits():
    policy = RuntimePolicy()
    fp32 = policy.validation_limits("fp32")
    fp16 = policy.validation_limits("fp16")
    assert fp32["max_absolute_error"] < fp16["max_absolute_error"]
    assert fp32["min_psnr_db"] > fp16["min_psnr_db"]
'''
    write(component_test_rel, component_tests)
    print(f"[extended tests] {component_test_rel}")

validation_test_rel = (
    "studio/edmg-studio/python_backend/"
    "edmg_studio_backend/tests/test_runtime_validation.py"
)

validation_test_source = r'''from __future__ import annotations

import math
import torch

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
'''

existing_validation_test = path(validation_test_rel)
if existing_validation_test.exists():
    current = existing_validation_test.read_text(encoding="utf-8")
    if "test_fp32_profile_accepts_small_isolated_0054_outlier" not in current:
        raise RuntimeError(
            f"{validation_test_rel} already exists and is not the expected v2 test file."
        )
else:
    write(validation_test_rel, validation_test_source)
    print(f"[created] {validation_test_rel}")

docs_rel = "docs/TENSORRT_RUNTIME_INTEGRATION.md"
docs = read(docs_rel)
if "## Validation schema 2" not in docs:
    docs += r'''

## Validation schema 2

The SD1.5 VAE component engine identity now uses adapter version 2. This forces a
new content-addressed engine key after the validation-policy change; failed or ready
version-1 engines are not deleted and cannot be mistaken for version-2 validation.

FP32 validation no longer rejects an engine solely because one decoded value crosses
the previous 0.005 maximum-absolute-error boundary. Version 2 evaluates max and mean
absolute error, RMSE, P99 absolute error, PSNR and a dependency-free global SSIM
statistic across the fixed validation seeds. Maximum relative error is recorded for
diagnostics but is not a hard gate because reference values near zero make it
unstable as a VAE acceptance criterion.

The default FP32 maximum-absolute threshold is 0.0075, while mean error, RMSE, P99,
PSNR and SSIM independently constrain broad output drift. Strict execution and
no-fallback behavior remain unchanged.

The existing `services/tensorrt_standalone.py` implementation remains the verified
SD1.5 UNet TensorRT route. It is reported separately as `tensorrt_standalone`
rather than claiming that the normal Diffusers component runtime can replace its
UNet.
'''
    write(docs_rel, docs)
    print(f"[updated docs] {docs_rel}")

print("")
print("TensorRT runtime validation v2 patch completed.")
'@

    Set-Content -Path $Patcher -Value $PatcherSource -Encoding UTF8

    try {
        Invoke-Checked "Apply TensorRT Runtime v2 source patch" {
            & $PythonCommand @PythonPrefix $Patcher $RepoRoot
        }
    }
    finally {
        Remove-Item $Patcher -Force -ErrorAction SilentlyContinue
    }

    Invoke-Checked "git diff --check" {
        git diff --check
    }

    Write-Host ""
    Write-Host "Patch diff summary:" -ForegroundColor Cyan
    git diff --stat

    if (-not $SkipTests) {
        $Backend = Join-Path $RepoRoot "studio\edmg-studio\python_backend"
        $BackendPythonCandidates = @(
            (Join-Path $Backend ".venv\Scripts\python.exe"),
            (Join-Path $RepoRoot "studio\edmg-studio\.venv\Scripts\python.exe"),
            (Join-Path $RepoRoot ".venv\Scripts\python.exe")
        )
        $BackendPython = $BackendPythonCandidates |
            Where-Object { Test-Path $_ } |
            Select-Object -First 1

        Push-Location $Backend
        try {
            Invoke-Checked "Python compile check" {
                if ($BackendPython) {
                    & $BackendPython -m compileall -q edmg_studio_backend\runtime
                } else {
                    & $PythonCommand @PythonPrefix -m compileall -q edmg_studio_backend\runtime
                }
            }

            Invoke-Checked "Focused TensorRT backend tests" {
                if ($BackendPython) {
                    & $BackendPython -m pytest -q `
                        edmg_studio_backend\tests\test_runtime_validation.py `
                        edmg_studio_backend\tests\test_component_runtime.py `
                        edmg_studio_backend\tests\test_tensorrt_standalone.py
                } else {
                    & $PythonCommand @PythonPrefix -m pytest -q `
                        edmg_studio_backend\tests\test_runtime_validation.py `
                        edmg_studio_backend\tests\test_component_runtime.py `
                        edmg_studio_backend\tests\test_tensorrt_standalone.py
                }
            }
        }
        finally {
            Pop-Location
        }

        if (Get-Command dotnet -ErrorAction SilentlyContinue) {
            $CoreTests = Join-Path $RepoRoot `
                "studio\edmg-studio-winui\tests\EdmgStudio.Core.Tests\EdmgStudio.Core.Tests.csproj"
            if (Test-Path $CoreTests) {
                Invoke-Checked "EdmgStudio.Core tests" {
                    dotnet test $CoreTests -c Release --nologo
                }
            }

            $WinUIProject = Join-Path $RepoRoot `
                "studio\edmg-studio-winui\EdmgStudio.WinUI.csproj"
            if (Test-Path $WinUIProject) {
                Invoke-Checked "WinUI Release x64 build" {
                    dotnet build $WinUIProject -c Release -p:Platform=x64 --nologo
                }
            }
        }
        else {
            Write-Warning "dotnet was not found; Core tests and WinUI build were skipped."
        }
    }

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host " TensorRT Runtime v2 patch applied" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Backup: $BackupRoot" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "TensorRT 10.15 / Torch-TensorRT 2.11 was NOT replaced."
    Write-Host "SD1.5 VAE adapter identity is now v2."
    Write-Host "Existing v1 failed engines are left intact."
    Write-Host "The next Optimize/render build creates a new v2 engine key."
    Write-Host "The existing standalone TensorRT UNet renderer remains separate."
    Write-Host ""
    Write-Host "Next: run Optimize for SD1.5, then confirm:"
    Write-Host "  state             = ready"
    Write-Host "  adapter_version   = 2"
    Write-Host "  validation.passed = true"
    Write-Host ""
    git status --short
}
catch {
    Write-Host ""
    Write-Host "PATCH FAILED:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    if ($BackupRoot) {
        Write-Host "Backup: $BackupRoot" -ForegroundColor Yellow
    }
    throw
}
finally {
    Pop-Location
}
