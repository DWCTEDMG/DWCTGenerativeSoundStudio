"""Record the Day 1 Studio performance baseline as machine-readable JSON."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "studio" / "edmg-studio" / "python_backend"
STUDIO_ROOT = REPO_ROOT / "studio" / "edmg-studio"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "day1"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "benchmarks" / "day1-baseline.json"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _run_text(command: list[str], *, cwd: Path = REPO_ROOT, timeout: float = 20.0) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return (completed.stdout or completed.stderr or "").strip()


def _first_line(command: list[str], *, cwd: Path = REPO_ROOT) -> str | None:
    text = _run_text(command, cwd=cwd)
    return text.splitlines()[0].strip() if text else None


def sanitize_text(value: object) -> str:
    """Redact user-home and temporary roots from publishable evidence strings."""

    text = str(value)
    replacements = sorted(
        {
            str(Path.home()): "<USER_HOME>",
            str(Path(tempfile.gettempdir())): "<TEMP>",
        }.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    for original, replacement in replacements:
        if not original:
            continue
        text = re.sub(re.escape(original), lambda _match: replacement, text, flags=re.IGNORECASE)
    return text


def _windows_hardware() -> dict[str, Any]:
    command = (
        "$cs=Get-CimInstance Win32_ComputerSystem;"
        "$cpu=Get-CimInstance Win32_Processor|Select-Object -First 1;"
        "$os=Get-CimInstance Win32_OperatingSystem;"
        "[PSCustomObject]@{manufacturer=$cs.Manufacturer;model=$cs.Model;"
        "ram_bytes=[int64]$cs.TotalPhysicalMemory;cpu=$cpu.Name;"
        "physical_cores=$cpu.NumberOfCores;logical_processors=$cpu.NumberOfLogicalProcessors;"
        "os=$os.Caption;os_version=$os.Version;os_build=$os.BuildNumber}|"
        "ConvertTo-Json -Compress"
    )
    raw = _run_text(["powershell", "-NoProfile", "-Command", command])
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _gpu_identity() -> dict[str, Any] | None:
    raw = _run_text(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    if not raw:
        return None
    name, separator, remainder = raw.split(",", 1)[0], ",", raw.partition(",")[2]
    if not separator or not remainder:
        return {"name": raw}
    memory, _, driver = remainder.partition(",")
    try:
        memory_mib: int | None = int(memory.strip())
    except ValueError:
        memory_mib = None
    return {"name": name.strip(), "memory_mib": memory_mib, "driver": driver.strip() or None}


def machine_identity() -> dict[str, Any]:
    disk = shutil.disk_usage(REPO_ROOT)
    hardware = _windows_hardware() if os.name == "nt" else {}
    hardware.setdefault("cpu", platform.processor() or platform.machine())
    hardware.setdefault("logical_processors", os.cpu_count())
    hardware.update(
        {
            "architecture": platform.machine(),
            "platform": platform.platform(),
            "gpu": _gpu_identity(),
            "workspace_disk": {
                "path": str(REPO_ROOT.drive or REPO_ROOT.anchor),
                "total_bytes": disk.total,
                "free_bytes": disk.free,
            },
        }
    )
    return hardware


def software_identity() -> dict[str, Any]:
    commit = _first_line(["git", "rev-parse", "HEAD"])
    status = _run_text(["git", "status", "--porcelain"])
    return {
        "git_commit": commit,
        "working_tree_dirty": bool(status),
        "python": platform.python_version(),
        "python_executable": sanitize_text(sys.executable),
        "uv": _first_line(["uv", "--version"]),
        "node": _first_line(["node", "--version"]),
        "pnpm": _first_line(_pnpm_command("--version")),
        "ffmpeg": _first_line(["ffmpeg", "-version"]),
    }


def summarize(samples_ms: list[float]) -> dict[str, Any]:
    if not samples_ms:
        raise ValueError("at least one timing sample is required")
    ordered = sorted(samples_ms)
    p95_index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * 0.95 + 0.5)))
    return {
        "status": "measured",
        "iterations": len(samples_ms),
        "samples_ms": [round(value, 3) for value in samples_ms],
        "min_ms": round(ordered[0], 3),
        "median_ms": round(statistics.median(ordered), 3),
        "mean_ms": round(statistics.fmean(ordered), 3),
        "p95_ms": round(ordered[p95_index], 3),
        "max_ms": round(ordered[-1], 3),
    }


def _measure(operation: Callable[[], Any], iterations: int) -> tuple[dict[str, Any], Any]:
    samples: list[float] = []
    last_value: Any = None
    for _ in range(max(1, iterations)):
        started = time.perf_counter_ns()
        last_value = operation()
        samples.append((time.perf_counter_ns() - started) / 1_000_000.0)
    return summarize(samples), last_value


def benchmark_project_open(iterations: int) -> dict[str, Any]:
    from edmg_studio_backend.contracts import adapt_legacy_project
    from edmg_studio_backend.store.projects import ProjectStore

    fixture = json.loads((FIXTURE_ROOT / "project" / "project.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="edmg-project-open-") as raw_root:
        store = ProjectStore(Path(raw_root) / "data")
        project_dir = store.project_dir(fixture["id"])
        (project_dir / "project.json").write_text(json.dumps(fixture), encoding="utf-8")

        def open_project():
            project = store.get(fixture["id"])
            if project is None:
                raise RuntimeError("project fixture could not be opened")
            return adapt_legacy_project(asdict(project))

        open_project()
        result, project = _measure(open_project, iterations)
    result.update(
        {
            "scope": "ProjectStore disk read plus legacy-to-v1 compatibility adapter",
            "fixture": "tests/fixtures/day1/project/project.json",
            "project_id": project.id,
        }
    )
    return result


def _timeline_payload() -> tuple[dict[str, Any], dict[str, Any]]:
    frame_count = 7_200
    schedule = ", ".join(f"{frame}:({1.0 + (frame % 300) / 3000.0:.4f})" for frame in range(0, frame_count, 15))
    payload = {
        "metadata": {"fps": 30, "duration": 240.0, "renderMode": "performance"},
        "schedules": {"zoom": schedule, "rotation_y": schedule, "translation_x": schedule},
        "sections": [
            {"id": f"section-{index}", "startTime": float(index * 10), "avgEnergy": 0.5}
            for index in range(24)
        ],
        "cue_events": [
            {"id": f"cue-{index}", "frame": index * 30, "time": float(index), "cueType": "beat"}
            for index in range(240)
        ],
        "repair_suggestions": [],
    }
    return {"tracks": [], "camera": {"keyframes": []}}, payload


def benchmark_timeline(iterations: int) -> dict[str, Any]:
    from edmg_studio_backend.services.workbench_bridge import merge_reactive_lab_into_timeline

    timeline, payload = _timeline_payload()
    result, merged = _measure(lambda: merge_reactive_lab_into_timeline(timeline, payload), iterations)
    camera = merged.get("camera") if isinstance(merged.get("camera"), dict) else {}
    result.update(
        {
            "scope": "Backend merge of a 240-second reactive timeline with 240 cues",
            "cue_count": len(payload["cue_events"]),
            "camera_keyframe_count": len(camera.get("keyframes") or []),
        }
    )
    return result


def benchmark_analysis(iterations: int) -> dict[str, Any]:
    from enhanced_deforum_music_generator.config.config_system import AudioConfig
    from enhanced_deforum_music_generator.core.audio_analyzer import AudioAnalyzer

    audio_path = FIXTURE_ROOT / "audio" / "tiny_pulse.wav"

    def analyze_audio():
        return AudioAnalyzer(AudioConfig(max_duration=5)).analyze(str(audio_path), enable_cache=False)

    result, analysis = _measure(analyze_audio, iterations)
    result.update(
        {
            "scope": "Full local librosa AudioAnalyzer pass with cache disabled",
            "fixture": "tests/fixtures/day1/audio/tiny_pulse.wav",
            "duration_seconds": round(float(analysis["duration"]), 3),
            "sample_rate": int(analysis["sample_rate"]),
        }
    )
    return result


def _isolated_environment(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    home = root / "studio-home"
    paths = {
        "EDMG_STUDIO_HOME": home,
        "EDMG_STUDIO_DATA_DIR": home / "data",
        "EDMG_STUDIO_MODELS_DIR": home / "models",
        "EDMG_STUDIO_CACHE_DIR": home / "cache",
        "EDMG_STUDIO_LOGS_DIR": home / "logs",
        "EDMG_STUDIO_EXTERNAL_DIR": home / "external",
        "OLLAMA_MODELS": home / "models" / "ollama",
    }
    for key, path in paths.items():
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    env.update(
        {
            "EDMG_BACKEND_AUTH_MODE": "disabled",
            "EDMG_STUDIO_BACKEND_HOST": "127.0.0.1",
            "EDMG_WORKER_AUTOSTART": "0",
        }
    )
    return env


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def benchmark_backend_launch(iterations: int) -> dict[str, Any]:
    samples: list[float] = []
    output_tail: list[str] = []
    for _ in range(max(1, iterations)):
        with tempfile.TemporaryDirectory(prefix="edmg-backend-launch-") as raw_root:
            root = Path(raw_root)
            env = _isolated_environment(root)
            port = _free_port()
            command = [
                sys.executable,
                "-m",
                "edmg_studio_backend",
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ]
            started = time.perf_counter_ns()
            process = subprocess.Popen(
                command,
                cwd=BACKEND_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            try:
                deadline = time.monotonic() + 30.0
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("backend exited before becoming healthy")
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as response:
                            if response.status == 200:
                                samples.append((time.perf_counter_ns() - started) / 1_000_000.0)
                                break
                    except (OSError, urllib.error.URLError):
                        time.sleep(0.025)
                else:
                    raise TimeoutError("backend did not become healthy within 30 seconds")
            finally:
                process.terminate()
                try:
                    stdout, _ = process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout, _ = process.communicate(timeout=5)
                output_tail = [sanitize_text(line) for line in (stdout or "").splitlines()[-8:]]
    result = summarize(samples)
    result.update(
        {
            "scope": "Source backend process start until HTTP /health returns 200",
            "command": "python -m edmg_studio_backend serve --host 127.0.0.1 --port <ephemeral>",
            "output_tail": output_tail,
        }
    )
    return result


def _pnpm_command(*args: str) -> list[str]:
    if os.name == "nt":
        return ["cmd.exe", "/d", "/s", "/c", "pnpm", *args]
    return ["pnpm", *args]


def benchmark_command(command: list[str], *, cwd: Path, scope: str, timeout: float) -> dict[str, Any]:
    started = time.perf_counter_ns()
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    elapsed = (time.perf_counter_ns() - started) / 1_000_000.0
    text = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    summary_lines = [
        sanitize_text(line.strip())
        for line in text.splitlines()
        if re.search(r"(passed|skipped|probe passed|Test Files|Tests\s+)", line, re.IGNORECASE)
    ][-12:]
    result = summarize([elapsed])
    result.update(
        {
            "status": "measured" if completed.returncode == 0 else "failed",
            "scope": scope,
            "command": sanitize_text(" ".join(command)),
            "exit_code": completed.returncode,
            "summary_lines": summary_lines,
        }
    )
    if completed.returncode != 0:
        result["output_tail"] = [sanitize_text(line) for line in text.splitlines()[-20:]]
    return result


def build_report(
    *,
    iterations: int,
    analysis_iterations: int,
    launch_iterations: int,
    include_electron: bool,
    include_tests: bool,
) -> dict[str, Any]:
    measurements: dict[str, Any] = {
        "backend_launch": benchmark_backend_launch(launch_iterations),
        "project_open": benchmark_project_open(iterations),
        "timeline_merge": benchmark_timeline(iterations),
        "audio_analysis": benchmark_analysis(analysis_iterations),
    }
    if include_electron:
        measurements["electron_smoke_launch"] = benchmark_command(
            _pnpm_command("run", "validate:desktop-integration:strict"),
            cwd=STUDIO_ROOT,
            scope="Instrumented Electron test-mode shell launch with mock backend",
            timeout=90.0,
        )
    else:
        measurements["electron_smoke_launch"] = {
            "status": "not_measured",
            "reason": "rerun with --include-electron on a host that can launch Electron",
        }
    if include_tests:
        measurements["python_test_scopes"] = benchmark_command(
            [sys.executable, str(REPO_ROOT / "scripts" / "run_pytest_scopes.py")],
            cwd=REPO_ROOT,
            scope="Repository and backend Python scope runner",
            timeout=600.0,
        )
    else:
        measurements["python_test_scopes"] = {
            "status": "not_measured",
            "reason": "rerun with --include-tests to record the complete Python scope wall time",
        }

    return {
        "schema_version": "1.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "machine": machine_identity(),
        "software": software_identity(),
        "methodology": {
            "clock": "time.perf_counter_ns",
            "local_iterations": max(1, iterations),
            "analysis_iterations": max(1, analysis_iterations),
            "launch_iterations": max(1, launch_iterations),
            "network_models_or_downloads": False,
        },
        "measurements": measurements,
        "limitations": [
            "Electron timing is an instrumented test-mode shell launch, not an installed production build launch.",
            "Project-open and timeline figures are backend operation probes, not browser paint or interaction latency.",
            "Audio analysis uses the one-second synthetic fixture with model transcription disabled.",
            "Render performance and GPU model quality belong to P5-02 and are not inferred from these timings.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--iterations", type=int, default=25)
    parser.add_argument("--analysis-iterations", type=int, default=3)
    parser.add_argument("--launch-iterations", type=int, default=1)
    parser.add_argument("--include-electron", action="store_true")
    parser.add_argument("--include-tests", action="store_true")
    args = parser.parse_args()
    report = build_report(
        iterations=max(1, args.iterations),
        analysis_iterations=max(1, args.analysis_iterations),
        launch_iterations=max(1, args.launch_iterations),
        include_electron=args.include_electron,
        include_tests=args.include_tests,
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote Day 1 baseline to {output}")
    failed = [name for name, value in report["measurements"].items() if value.get("status") == "failed"]
    if failed:
        print(f"failed measurements: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
