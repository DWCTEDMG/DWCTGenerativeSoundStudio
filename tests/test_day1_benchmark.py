from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "benchmark_day1_baseline.py"
RECORDED_RESULT = REPO_ROOT / "docs" / "benchmarks" / "day1-baseline-windows-2026-07-14.json"
SPEC = importlib.util.spec_from_file_location("benchmark_day1_baseline", SCRIPT_PATH)
assert SPEC and SPEC.loader
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def test_timing_summary_is_stable_and_uses_milliseconds() -> None:
    summary = benchmark.summarize([3.0, 1.0, 2.0, 4.0])

    assert summary == {
        "status": "measured",
        "iterations": 4,
        "samples_ms": [3.0, 1.0, 2.0, 4.0],
        "min_ms": 1.0,
        "median_ms": 2.5,
        "mean_ms": 2.5,
        "p95_ms": 4.0,
        "max_ms": 4.0,
    }
    with pytest.raises(ValueError, match="at least one"):
        benchmark.summarize([])


def test_project_open_probe_uses_frozen_compatibility_contract() -> None:
    result = benchmark.benchmark_project_open(2)

    assert result["status"] == "measured"
    assert result["iterations"] == 2
    assert result["project_id"] == "day1-fixture-project"
    assert "compatibility adapter" in result["scope"]


def test_timeline_probe_processes_reactive_cues() -> None:
    result = benchmark.benchmark_timeline(2)

    assert result["status"] == "measured"
    assert result["iterations"] == 2
    assert result["cue_count"] == 240
    assert result["camera_keyframe_count"] > 0


def test_machine_and_software_identity_are_json_safe() -> None:
    machine = benchmark.machine_identity()
    software = benchmark.software_identity()

    assert machine["logical_processors"]
    assert machine["workspace_disk"]["total_bytes"] > 0
    assert software["git_commit"]
    assert software["python"]
    assert software["pnpm"]
    assert str(Path.home()) not in software["python_executable"]


def test_publishable_evidence_redacts_user_and_temp_paths() -> None:
    source = f"{Path.home()} and {Path(benchmark.tempfile.gettempdir())}"
    sanitized = benchmark.sanitize_text(source)

    assert str(Path.home()) not in sanitized
    assert "<USER_HOME>" in sanitized
    assert "<TEMP>" in sanitized


def test_recorded_day1_result_is_complete_clean_and_redacted() -> None:
    raw = RECORDED_RESULT.read_text(encoding="utf-8")
    result = benchmark.json.loads(raw)

    assert result["schema_version"] == "1.0"
    assert result["software"]["working_tree_dirty"] is False
    assert len(result["software"]["git_commit"]) == 40
    assert str(Path.home()).lower() not in raw.lower()
    assert set(result["measurements"]) == {
        "backend_launch",
        "project_open",
        "timeline_merge",
        "audio_analysis",
        "electron_smoke_launch",
        "python_test_scopes",
    }
    for measurement in result["measurements"].values():
        assert measurement["status"] == "measured"
        assert measurement.get("exit_code", 0) == 0
