from __future__ import annotations

from dataclasses import asdict

import pytest

from edmg_studio_backend.execution.inventory import (
    CommandResult,
    GpuDiscoveryError,
    GpuObservation,
    discover_windows_gpus,
    discover_wsl_gpus,
    parse_nvidia_smi_inventory,
    reconcile_physical_gpus,
)
from edmg_studio_backend.services.model_runtime_registry import execution_inventory_status


WINDOWS_OUTPUT = """0, NVIDIA RTX A6000, GPU-AAAA, 00000000:21:00.0, 48140
1, NVIDIA RTX A6000, GPU-BBBB, 00000000:41:00.0, 48140
2, NVIDIA RTX A6000, GPU-CCCC, 00000000:61:00.0, 48140
"""

WSL_REORDERED_OUTPUT = """0, NVIDIA RTX A6000, GPU-CCCC, 0000:61:00.0, 48140
1, NVIDIA RTX A6000, GPU-AAAA, 0000:21:00.0, 48140
2, NVIDIA RTX A6000, GPU-BBBB, 0000:41:00.0, 48140
"""


class FakeRunner:
    def __init__(self, result: CommandResult | Exception):
        self.result = result
        self.calls: list[tuple[tuple[str, ...], float]] = []

    def run(self, args: tuple[str, ...], timeout_seconds: float) -> CommandResult:
        self.calls.append((args, timeout_seconds))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_parser_and_reconciliation_use_uuid_despite_reordered_indices() -> None:
    windows = parse_nvidia_smi_inventory(WINDOWS_OUTPUT, source="windows")
    wsl = parse_nvidia_smi_inventory(WSL_REORDERED_OUTPUT, source="wsl")
    physical = reconcile_physical_gpus(windows, wsl)

    assert [(gpu.uuid, gpu.windows_index, gpu.wsl_index) for gpu in physical] == [
        ("aaaa", 0, 1),
        ("bbbb", 1, 2),
        ("cccc", 2, 0),
    ]
    assert all(gpu.available_for_cross_environment for gpu in physical)
    assert all(gpu.memory_total_bytes == 48140 * 1024 * 1024 for gpu in physical)


def test_reconciliation_falls_back_to_normalized_pci_when_uuid_is_absent() -> None:
    windows = parse_nvidia_smi_inventory(
        "3, NVIDIA RTX A6000, N/A, 00000000:81:00.0, 48140\n",
        source="windows",
    )
    wsl = parse_nvidia_smi_inventory(
        "0, NVIDIA RTX A6000, N/A, 0000:81:00.0, 48140\n",
        source="wsl",
    )

    assert reconcile_physical_gpus(windows, wsl)[0].model_dump() == {
        "device_id": "gpu-pci:0000:81:00.0",
        "name": "NVIDIA RTX A6000",
        "uuid": None,
        "pci_bus_id": "0000:81:00.0",
        "memory_total_bytes": 48140 * 1024 * 1024,
        "windows_index": 3,
        "wsl_index": 0,
        "available_for_cross_environment": True,
        "availability_reason": None,
    }


def test_wsl_exposing_fewer_gpus_marks_unmatched_windows_device_unavailable() -> None:
    physical = reconcile_physical_gpus(
        parse_nvidia_smi_inventory(WINDOWS_OUTPUT, source="windows"),
        parse_nvidia_smi_inventory(WSL_REORDERED_OUTPUT.splitlines()[0] + "\n", source="wsl"),
    )

    unmatched = [gpu for gpu in physical if gpu.wsl_index is None]
    assert len(unmatched) == 2
    assert {gpu.availability_reason for gpu in unmatched} == {"not visible in WSL"}


def test_duplicate_identity_is_ambiguous_and_never_schedulable() -> None:
    duplicate = parse_nvidia_smi_inventory(
        "0, NVIDIA RTX A6000, GPU-AAAA, 0000:21:00.0, 48140\n"
        "1, NVIDIA RTX A6000, GPU-AAAA, 0000:22:00.0, 48140\n",
        source="wsl",
    )
    physical = reconcile_physical_gpus(
        parse_nvidia_smi_inventory(WINDOWS_OUTPUT.splitlines()[0] + "\n", source="windows"),
        duplicate,
    )

    assert physical
    assert not any(gpu.available_for_cross_environment for gpu in physical)
    assert all("ambiguous" in (gpu.availability_reason or "") for gpu in physical)


def test_discovery_builds_bounded_windows_and_wsl_commands() -> None:
    windows_runner = FakeRunner(CommandResult(0, WINDOWS_OUTPUT, ""))
    wsl_runner = FakeRunner(CommandResult(0, WSL_REORDERED_OUTPUT, ""))

    windows = discover_windows_gpus(windows_runner)
    wsl = discover_wsl_gpus(wsl_runner, "Ubuntu")

    assert len(windows) == 3
    assert len(wsl) == 3
    assert windows_runner.calls[0][0][0] == "nvidia-smi"
    assert wsl_runner.calls[0][0][:5] == (
        "wsl.exe",
        "--distribution",
        "Ubuntu",
        "--exec",
        "nvidia-smi",
    )
    assert windows_runner.calls[0][1] == 10.0
    assert wsl_runner.calls[0][1] == 10.0


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (TimeoutError("timed out"), "GPU_DISCOVERY_TIMEOUT"),
        (FileNotFoundError("wsl.exe"), "GPU_DISCOVERY_COMMAND_MISSING"),
    ],
)
def test_discovery_reports_timeout_and_missing_distribution_or_command(
    failure: Exception,
    code: str,
) -> None:
    with pytest.raises(GpuDiscoveryError) as caught:
        discover_wsl_gpus(FakeRunner(failure), "Ubuntu")
    assert caught.value.code == code

    missing_distro = FakeRunner(CommandResult(1, "", "There is no distribution with the supplied name"))
    with pytest.raises(GpuDiscoveryError) as caught:
        discover_wsl_gpus(missing_distro, "Missing")
    assert caught.value.code == "WSL_DISTRIBUTION_UNAVAILABLE"


def test_no_nvidia_hardware_returns_empty_inventory() -> None:
    runner = FakeRunner(CommandResult(0, "", ""))
    assert discover_windows_gpus(runner) == []
    assert reconcile_physical_gpus([], []) == []


def test_runtime_registry_inventory_status_separates_observations_and_physical_ids() -> None:
    windows = parse_nvidia_smi_inventory(WINDOWS_OUTPUT, source="windows")
    wsl = parse_nvidia_smi_inventory(WSL_REORDERED_OUTPUT, source="wsl")

    status = execution_inventory_status(windows, wsl)

    assert status["windows_observations"][0] == asdict(windows[0])
    assert status["wsl_observations"][0] == asdict(wsl[0])
    assert status["physical_gpus"][0]["device_id"] == "gpu-uuid:aaaa"
