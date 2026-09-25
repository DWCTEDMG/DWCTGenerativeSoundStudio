"""GPU discovery and Windows/WSL physical-device reconciliation."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Literal, Protocol, Sequence

from pydantic import Field

from .contracts import FrozenContract

GpuObservationSource = Literal["windows", "wsl"]

_QUERY_ARGUMENT = "index,name,uuid,pci.bus_id,memory.total"
_FORMAT_ARGUMENT = "csv,noheader,nounits"
_PCI_PATTERN = re.compile(
    r"^(?P<domain>[0-9a-fA-F]{4,8}):(?P<bus>[0-9a-fA-F]{2}):"
    r"(?P<device>[0-9a-fA-F]{2})\.(?P<function>[0-7])$"
)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(self, args: tuple[str, ...], timeout_seconds: float) -> CommandResult: ...


@dataclass(frozen=True)
class GpuObservation:
    source: GpuObservationSource
    index: int
    name: str
    uuid: str | None
    pci_bus_id: str | None
    memory_total_bytes: int


class PhysicalGpu(FrozenContract):
    device_id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=256)
    uuid: str | None = Field(default=None, min_length=1, max_length=160)
    pci_bus_id: str | None = Field(default=None, min_length=1, max_length=64)
    memory_total_bytes: int = Field(ge=0)
    windows_index: int | None = Field(default=None, ge=0)
    wsl_index: int | None = Field(default=None, ge=0)
    available_for_cross_environment: bool
    availability_reason: str | None = Field(default=None, min_length=1, max_length=500)


class GpuDiscoveryError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _normalize_uuid(value: str) -> str | None:
    normalized = value.strip().lower()
    if normalized in {"", "n/a", "none", "[not supported]"}:
        return None
    if normalized.startswith("gpu-"):
        normalized = normalized[4:]
    return normalized or None


def _normalize_pci_bus_id(value: str) -> str | None:
    normalized = value.strip()
    if normalized.lower() in {"", "n/a", "none", "[not supported]"}:
        return None
    match = _PCI_PATTERN.fullmatch(normalized)
    if not match:
        return None
    domain = match.group("domain")[-4:].lower()
    return (
        f"{domain}:{match.group('bus').lower()}:{match.group('device').lower()}."
        f"{match.group('function')}"
    )


def parse_nvidia_smi_inventory(
    output: str,
    *,
    source: GpuObservationSource,
) -> list[GpuObservation]:
    observations: list[GpuObservation] = []
    for row_number, row in enumerate(csv.reader(io.StringIO(output)), start=1):
        if not row or not any(value.strip() for value in row):
            continue
        if len(row) != 5:
            raise GpuDiscoveryError(
                "GPU_DISCOVERY_OUTPUT_INVALID",
                f"nvidia-smi row {row_number} contained {len(row)} fields instead of 5",
            )
        try:
            index = int(row[0].strip())
            memory_mib = int(row[4].strip())
        except ValueError as exc:
            raise GpuDiscoveryError(
                "GPU_DISCOVERY_OUTPUT_INVALID",
                f"nvidia-smi row {row_number} contained an invalid numeric field",
            ) from exc
        name = row[1].strip()
        if index < 0 or memory_mib < 0 or not name:
            raise GpuDiscoveryError(
                "GPU_DISCOVERY_OUTPUT_INVALID",
                f"nvidia-smi row {row_number} contained an invalid device value",
            )
        observations.append(
            GpuObservation(
                source=source,
                index=index,
                name=name,
                uuid=_normalize_uuid(row[2]),
                pci_bus_id=_normalize_pci_bus_id(row[3]),
                memory_total_bytes=memory_mib * 1024 * 1024,
            )
        )
    return observations


def _run_inventory(
    run: CommandRunner,
    args: tuple[str, ...],
    *,
    source: GpuObservationSource,
) -> list[GpuObservation]:
    try:
        result = run.run(args, 10.0)
    except TimeoutError as exc:
        raise GpuDiscoveryError("GPU_DISCOVERY_TIMEOUT", f"{source} GPU discovery timed out") from exc
    except FileNotFoundError as exc:
        raise GpuDiscoveryError(
            "GPU_DISCOVERY_COMMAND_MISSING",
            f"{args[0]} was not found",
        ) from exc
    except OSError as exc:
        raise GpuDiscoveryError("GPU_DISCOVERY_FAILED", str(exc)) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        lowered = detail.lower()
        if source == "wsl" and "distribution" in lowered and (
            "not" in lowered or "no " in lowered
        ):
            raise GpuDiscoveryError("WSL_DISTRIBUTION_UNAVAILABLE", detail)
        raise GpuDiscoveryError(
            "GPU_DISCOVERY_FAILED",
            detail or f"{args[0]} exited with code {result.returncode}",
        )
    return parse_nvidia_smi_inventory(result.stdout, source=source)


def discover_windows_gpus(run: CommandRunner) -> list[GpuObservation]:
    return _run_inventory(
        run,
        (
            "nvidia-smi",
            f"--query-gpu={_QUERY_ARGUMENT}",
            f"--format={_FORMAT_ARGUMENT}",
        ),
        source="windows",
    )


def discover_wsl_gpus(run: CommandRunner, distro: str) -> list[GpuObservation]:
    selected_distro = distro.strip()
    if not selected_distro:
        raise GpuDiscoveryError("WSL_DISTRIBUTION_UNAVAILABLE", "WSL distribution is required")
    return _run_inventory(
        run,
        (
            "wsl.exe",
            "--distribution",
            selected_distro,
            "--exec",
            "nvidia-smi",
            f"--query-gpu={_QUERY_ARGUMENT}",
            f"--format={_FORMAT_ARGUMENT}",
        ),
        source="wsl",
    )


def _identity_key(observation: GpuObservation) -> tuple[str, str] | None:
    if observation.uuid:
        return "uuid", observation.uuid
    if observation.pci_bus_id:
        return "pci", observation.pci_bus_id
    return None


def _device_id(uuid: str | None, pci_bus_id: str | None, suffix: str = "") -> str:
    if uuid:
        base = f"gpu-uuid:{uuid}"
    elif pci_bus_id:
        base = f"gpu-pci:{pci_bus_id}"
    else:
        base = "gpu-unidentified"
    return f"{base}{suffix}"


def _physical(
    windows: GpuObservation | None,
    wsl: GpuObservation | None,
    *,
    available: bool,
    reason: str | None,
    suffix: str = "",
) -> PhysicalGpu:
    observation = windows or wsl
    assert observation is not None
    uuid = (windows.uuid if windows else None) or (wsl.uuid if wsl else None)
    pci_bus_id = (windows.pci_bus_id if windows else None) or (wsl.pci_bus_id if wsl else None)
    memory = min(
        item.memory_total_bytes for item in (windows, wsl) if item is not None
    )
    return PhysicalGpu(
        device_id=_device_id(uuid, pci_bus_id, suffix),
        name=observation.name,
        uuid=uuid,
        pci_bus_id=pci_bus_id,
        memory_total_bytes=memory,
        windows_index=windows.index if windows else None,
        wsl_index=wsl.index if wsl else None,
        available_for_cross_environment=available,
        availability_reason=reason,
    )


def reconcile_physical_gpus(
    windows: Sequence[GpuObservation],
    wsl: Sequence[GpuObservation],
) -> list[PhysicalGpu]:
    """Reconcile devices by UUID, then PCI identity when UUID is unavailable."""

    windows_list = list(windows)
    wsl_list = list(wsl)
    key_counts: dict[tuple[str, str], dict[str, int]] = {}
    for observation in (*windows_list, *wsl_list):
        key = _identity_key(observation)
        if key is None:
            continue
        counts = key_counts.setdefault(key, {"windows": 0, "wsl": 0})
        counts[observation.source] += 1
    ambiguous = {
        key for key, counts in key_counts.items() if counts["windows"] > 1 or counts["wsl"] > 1
    }

    results: list[PhysicalGpu] = []
    consumed_wsl: set[int] = set()

    for windows_gpu in windows_list:
        key = _identity_key(windows_gpu)
        if key in ambiguous:
            results.append(
                _physical(
                    windows_gpu,
                    None,
                    available=False,
                    reason="ambiguous physical GPU identity",
                    suffix=f":ambiguous:windows:{windows_gpu.index}",
                )
            )
            continue

        candidates: list[tuple[int, GpuObservation]] = []
        for position, wsl_gpu in enumerate(wsl_list):
            if position in consumed_wsl or _identity_key(wsl_gpu) in ambiguous:
                continue
            if windows_gpu.uuid and wsl_gpu.uuid and windows_gpu.uuid == wsl_gpu.uuid:
                candidates.append((position, wsl_gpu))
                continue
            if (
                windows_gpu.pci_bus_id
                and windows_gpu.pci_bus_id == wsl_gpu.pci_bus_id
                and not (windows_gpu.uuid and wsl_gpu.uuid)
            ):
                candidates.append((position, wsl_gpu))
        if len(candidates) == 1:
            position, wsl_gpu = candidates[0]
            consumed_wsl.add(position)
            results.append(_physical(windows_gpu, wsl_gpu, available=True, reason=None))
        elif len(candidates) > 1:
            results.append(
                _physical(
                    windows_gpu,
                    None,
                    available=False,
                    reason="ambiguous physical GPU identity",
                )
            )
        else:
            results.append(
                _physical(windows_gpu, None, available=False, reason="not visible in WSL")
            )

    for position, wsl_gpu in enumerate(wsl_list):
        if position in consumed_wsl:
            continue
        key = _identity_key(wsl_gpu)
        if key in ambiguous:
            reason = "ambiguous physical GPU identity"
            suffix = f":ambiguous:wsl:{wsl_gpu.index}"
        else:
            reason = "not visible in Windows"
            suffix = ""
        results.append(
            _physical(windows=None, wsl=wsl_gpu, available=False, reason=reason, suffix=suffix)
        )

    return sorted(
        results,
        key=lambda item: (
            item.windows_index is None,
            item.windows_index if item.windows_index is not None else 10_000,
            item.wsl_index if item.wsl_index is not None else 10_000,
            item.device_id,
        ),
    )
