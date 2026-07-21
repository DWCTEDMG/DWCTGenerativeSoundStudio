from __future__ import annotations

import json
import os
import platform
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

SCHEMA_VERSION = 1

# Target budgets (ms) for W7-04 performance evidence — advisory until named-hardware runs land.
DEFAULT_BUDGETS_MS: dict[str, float] = {
    "launch": 8000.0,
    "project_open": 2000.0,
    "timeline_load": 1500.0,
    "analysis": 120_000.0,
    "render_plan": 5000.0,
    "render_enqueue": 3000.0,
    "pytest_scope_backend": 600_000.0,
}

_lock = threading.Lock()
_samples: dict[str, list[float]] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def record_baseline_sample(operation: str, duration_ms: float) -> None:
    """Record a timing sample for baseline metrics (in-process stub store)."""
    key = str(operation or "").strip()
    if not key:
        return
    value = max(0.0, float(duration_ms))
    with _lock:
        bucket = _samples.setdefault(key, [])
        bucket.append(value)
        if len(bucket) > 64:
            del bucket[:-64]


def reset_baseline_samples() -> None:
    with _lock:
        _samples.clear()


def _summary(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    count = len(ordered)
    return {
        "count": count,
        "last_ms": round(values[-1], 3),
        "min_ms": round(ordered[0], 3),
        "max_ms": round(ordered[-1], 3),
        "p50_ms": round(ordered[count // 2], 3),
        "mean_ms": round(sum(ordered) / count, 3),
    }


def _merge_env_samples() -> dict[str, list[float]]:
    raw = os.environ.get("EDMG_BASELINE_METRICS_JSON", "").strip()
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    merged: dict[str, list[float]] = {}
    for key, value in loaded.items():
        op = str(key or "").strip()
        if not op:
            continue
        if isinstance(value, (int, float)):
            merged[op] = [float(value)]
        elif isinstance(value, list):
            nums = [float(item) for item in value if isinstance(item, (int, float))]
            if nums:
                merged[op] = nums
    return merged


def collect_baseline_metrics(
    *,
    hardware_probe: Callable[[], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return read-only baseline timing counters and advisory budgets (P0-06 stub)."""
    with _lock:
        local_samples = {key: list(values) for key, values in _samples.items()}
    env_samples = _merge_env_samples()
    operations = sorted(set(local_samples) | set(env_samples) | set(DEFAULT_BUDGETS_MS))
    samples: dict[str, Any] = {}
    for op in operations:
        values = list(local_samples.get(op, [])) + list(env_samples.get(op, []))
        entry: dict[str, Any] = _summary(values)
        budget = DEFAULT_BUDGETS_MS.get(op)
        if budget is not None:
            entry["budget_ms"] = budget
            if values:
                entry["within_budget"] = float(values[-1]) <= float(budget)
        samples[op] = entry

    hardware: dict[str, Any] = {
        "host": platform.node() or "unknown",
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
    }
    if hardware_probe is not None:
        try:
            probed = dict(hardware_probe())
            if probed:
                hardware.update(probed)
        except Exception:
            pass

    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "collected_at": _utc_now(),
        "stub": True,
        "note": (
            "Baseline metrics are an in-process stub until W7-04 named-hardware runs publish "
            "immutable evidence. Set EDMG_BASELINE_METRICS_JSON to inject CI samples."
        ),
        "hardware": hardware,
        "budgets_ms": dict(DEFAULT_BUDGETS_MS),
        "samples": samples,
    }


class baseline_timer:
    """Context manager that records elapsed milliseconds for an operation."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        self._start = 0.0

    def __enter__(self) -> baseline_timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        elapsed_ms = (time.perf_counter() - self._start) * 1000.0
        record_baseline_sample(self.operation, elapsed_ms)
